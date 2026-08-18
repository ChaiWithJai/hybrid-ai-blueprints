# Deal Room Analyst v0.1.0 verification report

Date: August 18, 2026

This record certifies the repository structure and the local demonstration path. It does not certify model accuracy, economic value, production security, or clean machine reproduction.

## Result

The engineering release passed.

- The catalog resolves one use case and one blueprint.
- All local documentation links resolve.
- The full Python test suite passed with 523 tests.
- The host and live preflight checks passed.
- LM Studio reported Bonsai 27B as loaded and ready.
- Buzz relay was live at `http://127.0.0.1:3030`.
- The canonical deal room loaded at `http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass`.
- The browser showed the deal overview, four source files, the Bonsai 27B ready state, and the evaluation review queue.
- The browser console reported no warnings or errors during this check.

## Verification boundary

The Project Titan files are synthetic demonstration fixtures. The visible first pass includes an evidence safe fallback because an earlier Bonsai candidate failed deterministic source checks. This is useful evidence that the publication guard works. It is not evidence that Bonsai passed the deal analysis benchmark.

The benchmark remains in development. Domain blind review, evaluator calibration, cloud and hybrid comparison, and the pricing exercise remain separate milestones.

The preflight also reported that optional deployment metadata was absent. A benchmark claim still requires the local model artifact hash, runtime name and version, and hardware details.

## Source commit

The platform implementation under test is commit `32048929028e4aaec867e6061da8d21bc3823b4e`.
