package gateway

import (
	"errors"
	"testing"
)

func TestMemoryQueueEnqueueAndReceive(t *testing.T) {
	q := NewMemoryQueue(1)
	if err := q.Enqueue(Job{RunID: 7}); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if got := (<-q.Jobs()).RunID; got != 7 {
		t.Fatalf("RunID = %d, want 7", got)
	}
}

func TestMemoryQueueFullDoesNotBlock(t *testing.T) {
	q := NewMemoryQueue(1)
	_ = q.Enqueue(Job{RunID: 1})
	if err := q.Enqueue(Job{RunID: 2}); !errors.Is(err, ErrQueueFull) {
		t.Fatalf("Enqueue() error = %v, want ErrQueueFull", err)
	}
}
