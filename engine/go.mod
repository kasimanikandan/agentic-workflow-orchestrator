module github.com/org/orchestrator

go 1.21

// Core engine: no external deps — pure stdlib.
// The transport/grpc package adds these when you run `make proto`:
//   google.golang.org/grpc v1.64.0
//   google.golang.org/protobuf v1.34.2
