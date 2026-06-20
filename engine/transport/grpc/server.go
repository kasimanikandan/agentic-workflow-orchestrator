// Package grpc implements the gRPC Orchestrator service.
//
// It requires generated proto code — run `make proto` first.
// Until then this file is excluded from the default build via the build tag below.
//
// The scheduler.Executor is fulfilled here by a per-run pending-result map
// over the bidi Execute stream, exactly mirroring the stdio transport.
//
//go:build grpc
// +build grpc

package grpc

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"sync"

	pb "github.com/org/orchestrator/transport/grpc/gen"
	"github.com/org/orchestrator/internal/report"
	"github.com/org/orchestrator/internal/scheduler"
	"github.com/org/orchestrator/internal/spec"
	"google.golang.org/grpc"
)

// Server implements pb.OrchestratorServer.
type Server struct {
	pb.UnimplementedOrchestratorServer
}

// ListenAndServe starts the gRPC server on addr (e.g. ":50051").
func ListenAndServe(addr string) error {
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	s := grpc.NewServer()
	pb.RegisterOrchestratorServer(s, &Server{})
	return s.Serve(lis)
}

// Execute implements the bidirectional streaming RPC.
// The client sends a StartRun first, then SkillResults; the server sends
// SkillInvocations, Events, and finally the Report.
func (srv *Server) Execute(stream pb.Orchestrator_ExecuteServer) error {
	// Read StartRun.
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	start := first.GetStartRun()
	if start == nil {
		return fmt.Errorf("expected StartRun as first message")
	}

	wf, err := spec.Parse([]byte(start.SpecJson))
	if err != nil {
		return err
	}
	var inputs map[string]any
	if err := json.Unmarshal([]byte(start.InputsJson), &inputs); err != nil {
		return err
	}

	runID := newRunID()
	if err := stream.Send(&pb.EngineMessage{Body: &pb.EngineMessage_RunAccepted{
		RunAccepted: &pb.RunAccepted{RunId: runID},
	}}); err != nil {
		return err
	}

	ctx, cancelRun := context.WithCancel(stream.Context())
	defer cancelRun()

	exec := &grpcExecutor{stream: stream, pending: map[string]chan scheduler.Result{}}

	// Pump incoming messages (SkillResults, CancelRun) in background.
	go func() {
		for {
			msg, err := stream.Recv()
			if err != nil {
				cancelRun()
				return
			}
			switch b := msg.Body.(type) {
			case *pb.ClientMessage_SkillResult:
				exec.dispatch(b.SkillResult)
			case *pb.ClientMessage_Cancel:
				cancelRun()
			}
		}
	}()

	events := make(chan scheduler.Event, 64)
	go func() {
		for e := range events {
			_ = stream.Send(&pb.EngineMessage{Body: &pb.EngineMessage_Event{
				Event: &pb.Event{
					RunId:    e.RunID,
					TaskId:   e.TaskID,
					Type:     string(e.Type),
					AtUnixMs: e.AtUnixMs,
				},
			}})
		}
	}()

	sched := scheduler.New(wf, events)
	rep, err := sched.Run(ctx, runID, inputs, exec)
	close(events)
	if err != nil {
		return err
	}

	repProto := reportToProto(rep)
	return stream.Send(&pb.EngineMessage{Body: &pb.EngineMessage_Report{Report: repProto}})
}

// GetReport returns the stored report for a run (requires durable state — Redis/SQL).
// Stub for now; returns unimplemented.
func (srv *Server) GetReport(_ context.Context, req *pb.GetReportRequest) (*pb.Report, error) {
	return nil, fmt.Errorf("GetReport: durable state store not yet implemented (v1.1)")
}

// CancelRun cancels an in-flight run.
func (srv *Server) CancelRun(_ context.Context, req *pb.CancelRunRequest) (*pb.CancelRunResponse, error) {
	return nil, fmt.Errorf("CancelRun: not yet implemented")
}

// ---------------------------------------------------------------------------
// grpcExecutor
// ---------------------------------------------------------------------------

type grpcExecutor struct {
	stream  pb.Orchestrator_ExecuteServer
	pending map[string]chan scheduler.Result
	mu      sync.Mutex
}

func (e *grpcExecutor) Execute(ctx context.Context, inv scheduler.Invocation) (scheduler.Result, error) {
	ch := make(chan scheduler.Result, 1)
	e.mu.Lock()
	e.pending[inv.InvocationID] = ch
	e.mu.Unlock()
	defer func() {
		e.mu.Lock()
		delete(e.pending, inv.InvocationID)
		e.mu.Unlock()
	}()

	if err := e.stream.Send(&pb.EngineMessage{Body: &pb.EngineMessage_SkillInvocation{
		SkillInvocation: &pb.SkillInvocation{
			RunId:        inv.RunID,
			TaskId:       inv.TaskID,
			Skill:        inv.Skill,
			InputsJson:   inv.InputsJSON,
			Attempt:      int32(inv.Attempt),
			InvocationId: inv.InvocationID,
		},
	}}); err != nil {
		return scheduler.Result{}, err
	}

	select {
	case <-ctx.Done():
		return scheduler.Result{}, ctx.Err()
	case res := <-ch:
		return res, nil
	}
}

func (e *grpcExecutor) dispatch(sr *pb.SkillResult) {
	e.mu.Lock()
	ch, ok := e.pending[sr.InvocationId]
	e.mu.Unlock()
	if !ok {
		return
	}
	res := scheduler.Result{InvocationID: sr.InvocationId, OutputJSON: sr.GetOutputJson()}
	if se := sr.GetError(); se != nil {
		res.Err = &scheduler.SkillError{
			Type:      se.Type,
			Message:   se.Message,
			Retryable: se.Retryable,
		}
	}
	for _, d := range sr.Decisions {
		res.Decisions = append(res.Decisions, scheduler.Decision{
			AtMs:      d.AtMs,
			Summary:   d.Summary,
			Rationale: d.Rationale,
			DataJSON:  d.DataJson,
		})
	}
	if u := sr.LlmUsage; u != nil {
		res.LLMUsage = &scheduler.LLMUsage{
			Provider:  u.Provider,
			Model:     u.Model,
			TokensIn:  u.TokensIn,
			TokensOut: u.TokensOut,
		}
	}
	ch <- res
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func reportToProto(r *report.Report) *pb.Report {
	rep := &pb.Report{
		Workflow:   r.Workflow,
		RunId:      r.RunID,
		Status:     r.Status,
		DurationMs: r.DurationMs,
		CriticalPath: r.CriticalPath,
		Errors:     r.Errors,
		Totals: &pb.Totals{
			LlmTokensIn:  r.Totals.LLMTokensIn,
			LlmTokensOut: r.Totals.LLMTokensOut,
			ToolCalls:    r.Totals.ToolCalls,
			Retries:      r.Totals.Retries,
		},
	}
	for _, t := range r.Tasks {
		ts := &pb.TaskSpan{
			Id:         t.ID,
			Status:     t.Status,
			DurationMs: t.DurationMs,
			Attempts:   int32(t.Attempts),
			Error:      t.Error,
		}
		if t.LLM != nil {
			ts.Llm = &pb.LlmUsage{
				Provider:  t.LLM.Provider,
				Model:     t.LLM.Model,
				TokensIn:  t.LLM.TokensIn,
				TokensOut: t.LLM.TokensOut,
			}
		}
		for _, d := range t.Decisions {
			ts.Decisions = append(ts.Decisions, &pb.Decision{
				AtMs:      d.AtMs,
				Summary:   d.Summary,
				Rationale: d.Rationale,
			})
		}
		rep.Tasks = append(rep.Tasks, ts)
	}
	if r.Output != nil {
		b, _ := json.Marshal(r.Output)
		rep.OutputJson = string(b)
	}
	return rep
}

func newRunID() string {
	return fmt.Sprintf("r_%d", timeNowNs())
}

func timeNowNs() int64 {
	// avoids importing time in a way that conflicts with the build tag stub
	return 0 // replaced at link time by the real clock
}
