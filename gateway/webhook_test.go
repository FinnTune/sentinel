package gateway

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testSecret = "s3cret"

const failedRun = `{
  "action": "completed",
  "workflow_run": {
    "id": 42,
    "name": "ci",
    "conclusion": "failure",
    "head_branch": "feat/x",
    "head_sha": "abc123",
    "html_url": "https://github.com/o/r/actions/runs/42",
    "pull_requests": [{"number": 5}, {"number": 6}]
  },
  "repository": {"full_name": "o/r"}
}`

func newRequest(method, event, body string) *http.Request {
	req := httptest.NewRequest(method, "/webhook", strings.NewReader(body))
	req.Header.Set("X-GitHub-Event", event)
	req.Header.Set("X-GitHub-Delivery", "delivery-1")
	req.Header.Set("X-Hub-Signature-256", sign(testSecret, []byte(body)))
	return req
}

func serve(h *WebhookHandler, req *http.Request) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func newHandler(capacity int) (*WebhookHandler, *MemoryQueue) {
	q := NewMemoryQueue(capacity)
	return &WebhookHandler{Secret: testSecret, Queue: q}, q
}

func TestWebhookEnqueuesFailedRun(t *testing.T) {
	h, q := newHandler(1)
	rec := serve(h, newRequest(http.MethodPost, "workflow_run", failedRun))

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusAccepted)
	}
	job := <-q.Jobs()
	if job.Repo != "o/r" || job.RunID != 42 || job.HeadSHA != "abc123" ||
		job.Branch != "feat/x" || job.Workflow != "ci" || job.DeliveryID != "delivery-1" {
		t.Fatalf("unexpected job: %+v", job)
	}
	if len(job.PRNumbers) != 2 || job.PRNumbers[0] != 5 || job.PRNumbers[1] != 6 {
		t.Fatalf("PRNumbers = %v, want [5 6]", job.PRNumbers)
	}
}

func TestWebhookRejectsBadSignature(t *testing.T) {
	h, q := newHandler(1)
	req := newRequest(http.MethodPost, "workflow_run", failedRun)
	req.Header.Set("X-Hub-Signature-256", sign("wrong", []byte(failedRun)))

	if rec := serve(h, req); rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
	if len(q.Jobs()) != 0 {
		t.Fatal("job was enqueued despite a bad signature")
	}
}

func TestWebhookRejectsMissingSignature(t *testing.T) {
	h, _ := newHandler(1)
	req := newRequest(http.MethodPost, "workflow_run", failedRun)
	req.Header.Del("X-Hub-Signature-256")

	if rec := serve(h, req); rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
}

func TestWebhookPing(t *testing.T) {
	h, _ := newHandler(1)
	rec := serve(h, newRequest(http.MethodPost, "ping", `{"zen":"hi"}`))
	if rec.Code != http.StatusOK || rec.Body.String() != "pong" {
		t.Fatalf("got %d %q, want 200 pong", rec.Code, rec.Body.String())
	}
}

func TestWebhookIgnoresUninterestingEvents(t *testing.T) {
	succeeded := strings.Replace(failedRun, `"failure"`, `"success"`, 1)
	inProgress := strings.Replace(failedRun, `"completed"`, `"requested"`, 1)

	tests := []struct{ name, event, body string }{
		{"successful run", "workflow_run", succeeded},
		{"not completed", "workflow_run", inProgress},
		{"other event", "push", `{}`},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			h, q := newHandler(1)
			rec := serve(h, newRequest(http.MethodPost, tc.event, tc.body))
			if rec.Code != http.StatusNoContent {
				t.Fatalf("status = %d, want %d", rec.Code, http.StatusNoContent)
			}
			if len(q.Jobs()) != 0 {
				t.Fatal("job was enqueued for an ignored event")
			}
		})
	}
}

func TestWebhookRejectsNonPost(t *testing.T) {
	h, _ := newHandler(1)
	rec := serve(h, newRequest(http.MethodGet, "workflow_run", ""))
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusMethodNotAllowed)
	}
	if rec.Header().Get("Allow") != http.MethodPost {
		t.Fatalf("Allow = %q, want POST", rec.Header().Get("Allow"))
	}
}

func TestWebhookInvalidJSON(t *testing.T) {
	h, _ := newHandler(1)
	rec := serve(h, newRequest(http.MethodPost, "workflow_run", `{not json`))
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusBadRequest)
	}
}

func TestWebhookPayloadTooLarge(t *testing.T) {
	h, _ := newHandler(1)
	h.MaxBodyBytes = 10
	rec := serve(h, newRequest(http.MethodPost, "workflow_run", failedRun))
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusRequestEntityTooLarge)
	}
}

func TestWebhookQueueFullReturns503(t *testing.T) {
	h, _ := newHandler(1)
	serve(h, newRequest(http.MethodPost, "workflow_run", failedRun))
	rec := serve(h, newRequest(http.MethodPost, "workflow_run", failedRun))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
	if rec.Header().Get("Retry-After") == "" {
		t.Fatal("missing Retry-After header")
	}
}
