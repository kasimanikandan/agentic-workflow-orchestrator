package ratelimit

import (
	"context"
	"testing"
	"time"
)

func TestBucket_immediate(t *testing.T) {
	b := New(10, 1, "test") // 10 tokens / 1s
	ctx := context.Background()
	// First 10 acquires should be instant (bucket starts full).
	t0 := time.Now()
	for i := 0; i < 10; i++ {
		if err := b.Acquire(ctx); err != nil {
			t.Fatalf("acquire %d: %v", i, err)
		}
	}
	if time.Since(t0) > 50*time.Millisecond {
		t.Errorf("first 10 acquires should be instant, took %v", time.Since(t0))
	}
}

func TestBucket_throttles(t *testing.T) {
	// 5 tokens / 1s => 6th token needs ~0.2s to refill.
	b := New(5, 1, "test")
	ctx := context.Background()
	for i := 0; i < 5; i++ {
		_ = b.Acquire(ctx)
	}
	t0 := time.Now()
	if err := b.Acquire(ctx); err != nil {
		t.Fatal(err)
	}
	if time.Since(t0) < 150*time.Millisecond {
		t.Errorf("6th acquire should have waited, took %v", time.Since(t0))
	}
}

func TestBucket_cancelledContext(t *testing.T) {
	b := New(1, 1, "test")
	_ = b.Acquire(context.Background()) // drain
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := b.Acquire(ctx)
	if err == nil {
		t.Fatal("expected context deadline exceeded")
	}
}

func TestNullBucket(t *testing.T) {
	nb := NullBucket{}
	if err := nb.Acquire(context.Background()); err != nil {
		t.Fatalf("NullBucket.Acquire: %v", err)
	}
	if err := nb.AcquireN(context.Background(), 1000); err != nil {
		t.Fatalf("NullBucket.AcquireN: %v", err)
	}
}
