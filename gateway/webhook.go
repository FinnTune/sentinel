package gateway

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
)

// DefaultMaxBodyBytes caps webhook payloads. GitHub allows up to 25 MB, but
// workflow_run events are far smaller.
const DefaultMaxBodyBytes = 1 << 20

// WebhookHandler receives GitHub webhooks and enqueues triage jobs for failed
// workflow runs.
type WebhookHandler struct {
	Secret       string
	Queue        Queue
	MaxBodyBytes int64
}

type workflowRunEvent struct {
	Action      string `json:"action"`
	WorkflowRun struct {
		ID           int64  `json:"id"`
		Name         string `json:"name"`
		Conclusion   string `json:"conclusion"`
		HeadBranch   string `json:"head_branch"`
		HeadSHA      string `json:"head_sha"`
		HTMLURL      string `json:"html_url"`
		PullRequests []struct {
			Number int `json:"number"`
		} `json:"pull_requests"`
	} `json:"workflow_run"`
	Repository struct {
		FullName string `json:"full_name"`
	} `json:"repository"`
}

func (h *WebhookHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	limit := h.MaxBodyBytes
	if limit <= 0 {
		limit = DefaultMaxBodyBytes
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, limit))
	if err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			http.Error(w, "payload too large", http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, "cannot read body", http.StatusBadRequest)
		return
	}

	// Authenticate before looking at anything else in the request.
	if !VerifySignature(h.Secret, body, r.Header.Get("X-Hub-Signature-256")) {
		http.Error(w, "invalid signature", http.StatusUnauthorized)
		return
	}

	switch event := r.Header.Get("X-GitHub-Event"); event {
	case "ping":
		_, _ = io.WriteString(w, "pong")
	case "workflow_run":
		h.handleWorkflowRun(w, body, r.Header.Get("X-GitHub-Delivery"))
	default:
		w.WriteHeader(http.StatusNoContent)
	}
}

func (h *WebhookHandler) handleWorkflowRun(w http.ResponseWriter, body []byte, deliveryID string) {
	var ev workflowRunEvent
	if err := json.Unmarshal(body, &ev); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if ev.Action != "completed" || ev.WorkflowRun.Conclusion != "failure" {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	run := ev.WorkflowRun
	job := Job{
		DeliveryID: deliveryID,
		Repo:       ev.Repository.FullName,
		RunID:      run.ID,
		Workflow:   run.Name,
		Branch:     run.HeadBranch,
		HeadSHA:    run.HeadSHA,
		RunURL:     run.HTMLURL,
	}
	for _, pr := range run.PullRequests {
		job.PRNumbers = append(job.PRNumbers, pr.Number)
	}

	if err := h.Queue.Enqueue(job); err != nil {
		log.Printf("webhook: enqueue %s run %d: %v", job.Repo, job.RunID, err)
		w.Header().Set("Retry-After", "30")
		http.Error(w, "queue unavailable", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusAccepted)
}
