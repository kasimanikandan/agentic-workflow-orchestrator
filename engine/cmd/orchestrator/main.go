// orchestrator — the shared workflow orchestration engine.
//
// Modes:
//
//	embedded (default): reads one workflow run from stdin (NDJSON), executes it,
//	  streams events + final report to stdout. Spawned by the Python/Java/JS SDKs.
//
//	server: starts a gRPC service on --addr (default :50051).
//	  Requires `make proto` + the `grpc` build tag.
//	  Build: go build -tags grpc -o orchestrator ./cmd/orchestrator
//
// Usage (embedded mode):
//
//	echo '{"type":"start_run","spec_json":"{...}","inputs_json":"{...}"}' | ./orchestrator
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/org/orchestrator/internal/scheduler"
	"github.com/org/orchestrator/internal/spec"
	"github.com/org/orchestrator/transport/stdio"
)

func main() {
	mode := flag.String("mode", "embedded", "embedded | server")
	addr := flag.String("addr", ":50051", "gRPC listen address (server mode)")
	flag.Parse()

	switch *mode {
	case "embedded":
		runEmbedded()
	case "server":
		runServer(*addr)
	default:
		log.Fatalf("unknown mode %q (use embedded or server)", *mode)
	}
}

// ---------------------------------------------------------------------------
// Embedded mode
// ---------------------------------------------------------------------------

func runEmbedded() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	tr := stdio.NewTransport(os.Stdin, os.Stdout)

	specJSON, inputsJSON, err := tr.ReadStartRun()
	if err != nil {
		fatal(tr, fmt.Sprintf("reading start_run: %v", err))
		return
	}

	wf, err := spec.Parse([]byte(specJSON))
	if err != nil {
		fatal(tr, fmt.Sprintf("spec error: %v", err))
		return
	}

	var inputs map[string]any
	if inputsJSON == "" || inputsJSON == "null" {
		inputs = map[string]any{}
	} else if err := json.Unmarshal([]byte(inputsJSON), &inputs); err != nil {
		fatal(tr, fmt.Sprintf("inputs parse error: %v", err))
		return
	}

	// Validate required inputs.
	for name, schema := range wf.InputsSchema {
		if schema.Required {
			if _, ok := inputs[name]; !ok {
				fatal(tr, fmt.Sprintf("missing required input: %q", name))
				return
			}
		}
	}

	runID := fmt.Sprintf("r_%x", time.Now().UnixNano())
	if err := tr.SendRunAccepted(runID); err != nil {
		log.Fatalf("sending run_accepted: %v", err)
	}

	// Event fan-out.
	events := make(chan scheduler.Event, 128)
	go func() {
		for e := range events {
			_ = tr.SendEvent(e)
		}
	}()

	// Pump incoming skill_results + cancellations in background.
	runCtx, cancelRun := context.WithCancel(ctx)
	go tr.PumpIncoming(runCtx, cancelRun)

	sched := scheduler.New(wf, events)
	rep, err := sched.Run(runCtx, runID, inputs, tr)
	close(events)
	if err != nil {
		fatal(tr, fmt.Sprintf("run error: %v", err))
		return
	}

	if err := tr.SendReport(rep); err != nil {
		log.Fatalf("sending report: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Server mode (gRPC)
// ---------------------------------------------------------------------------

func runServer(addr string) {
	// Server mode requires the grpc build tag and generated proto code.
	// Build with: go build -tags grpc -o orchestrator ./cmd/orchestrator
	log.Fatalf("server mode: build with -tags grpc (see Makefile)")
}

// ---------------------------------------------------------------------------
// Error helper
// ---------------------------------------------------------------------------

func fatal(tr *stdio.Transport, msg string) {
	type errMsg struct {
		Type  string `json:"type"`
		Error string `json:"error"`
	}
	// Best-effort: send a structured error before dying.
	_ = tr.SendReport(errMsg{Type: "error", Error: msg})
	log.Fatalf("orchestrator: %s", msg)
}
