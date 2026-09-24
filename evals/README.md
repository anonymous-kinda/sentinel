# Routing eval set

`routing.jsonl`: 60 operator requests, each labelled with the call a careful
operator would expect: the catalogued tool and its arguments, or
`"tool": null` when the assistant should not act at all (out of scope, or a
request to compute or change something no tool does).

- Events are named by the exercise scenario's secondary catalog numbers
  (`99118` etc.) and resolved against the node's routing context at run time.
- The labels were written by the developer before either router was run on
  them. The deterministic router's rules predate the set and were not tuned
  on it. This is a small, developer-written set, not an operator corpus.
  Read the numbers as a comparison between routers on the same requests,
  not as field accuracy.

Run `make ai-eval` to regenerate `docs/ai-eval.md`. The deterministic
baseline always runs. Jev runs only when `TYPESAFE_API_KEY` is set, and
its numbers come only from that run.
