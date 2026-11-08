package gateway

import "errors"

// ErrQueueFull is returned when a job cannot be accepted right now.
var ErrQueueFull = errors.New("queue full")

// Job describes one failed CI run to triage.
type Job struct {
	DeliveryID string `json:"delivery_id"`
	Repo       string `json:"repo"`
	RunID      int64  `json:"run_id"`
	Workflow   string `json:"workflow"`
	Branch     string `json:"branch"`
	HeadSHA    string `json:"head_sha"`
	RunURL     string `json:"run_url"`
	PRNumbers  []int  `json:"pr_numbers,omitempty"`
}

// Queue accepts jobs for later processing.
type Queue interface {
	// Enqueue must not block: it returns ErrQueueFull when at capacity.
	Enqueue(Job) error
}

// MemoryQueue is a bounded in-process queue.
type MemoryQueue struct {
	jobs chan Job
}

// NewMemoryQueue returns a queue holding at most capacity pending jobs.
func NewMemoryQueue(capacity int) *MemoryQueue {
	return &MemoryQueue{jobs: make(chan Job, capacity)}
}

// Enqueue adds j without blocking.
func (q *MemoryQueue) Enqueue(j Job) error {
	select {
	case q.jobs <- j:
		return nil
	default:
		return ErrQueueFull
	}
}

// Jobs returns the channel consumers read pending jobs from.
func (q *MemoryQueue) Jobs() <-chan Job {
	return q.jobs
}
