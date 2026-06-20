// Package ratelimit provides a goroutine-safe token-bucket rate limiter.
// A task must acquire a token before it runs; if none are available
// the goroutine blocks until the bucket refills — non-blocking to the scheduler
// because each task runs in its own goroutine.
package ratelimit

import (
	"context"
	"sync"
	"time"
)

// Bucket is a token-bucket rate limiter.
type Bucket struct {
	mu       sync.Mutex
	tokens   float64
	capacity float64
	rate     float64 // tokens per second
	updated  time.Time
	name     string
}

// New creates a bucket that refills at rate/per (e.g. 60 tokens per 60s = 1/s).
// Capacity equals rate (burst = 1 window).
func New(rate float64, per float64, name string) *Bucket {
	capacity := rate
	return &Bucket{
		tokens:   capacity,
		capacity: capacity,
		rate:     rate / per,
		updated:  time.Now(),
		name:     name,
	}
}

// Acquire blocks until one token is available or ctx is cancelled.
func (b *Bucket) Acquire(ctx context.Context) error {
	return b.AcquireN(ctx, 1.0)
}

// AcquireN blocks until n tokens are available.
func (b *Bucket) AcquireN(ctx context.Context, n float64) error {
	for {
		b.mu.Lock()
		b.refill()
		if b.tokens >= n {
			b.tokens -= n
			b.mu.Unlock()
			return nil
		}
		deficit := n - b.tokens
		wait := time.Duration(float64(time.Second) * deficit / b.rate)
		b.mu.Unlock()

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(wait):
		}
	}
}

func (b *Bucket) refill() {
	now := time.Now()
	elapsed := now.Sub(b.updated).Seconds()
	b.tokens += elapsed * b.rate
	if b.tokens > b.capacity {
		b.tokens = b.capacity
	}
	b.updated = now
}

// ---------------------------------------------------------------------------
// NullBucket — no-op when no rate limit is configured
// ---------------------------------------------------------------------------

type NullBucket struct{}

func (NullBucket) Acquire(_ context.Context) error             { return nil }
func (NullBucket) AcquireN(_ context.Context, _ float64) error { return nil }

// Limiter is the common interface both types satisfy.
type Limiter interface {
	Acquire(ctx context.Context) error
	AcquireN(ctx context.Context, n float64) error
}
