# v2 release notes for maintainers

This branch introduces a private-workflow major version. Review and publish it as a new v2 release. Keep all existing v1 release tags and the v1 alias unchanged; do not force-move v1 to this implementation. No release or Marketplace publication is performed by these instructions.

Before publishing:

1. Run `python3 -m unittest discover -s tests -v` and `git diff --check`.
2. Review `action.yml` context bindings, the fixed API origins, redirect refusal and constant error messages in `fetch_odds.py`.
3. Confirm the migration notes explain private-repository verification, temporary output paths, CSV timestamp columns, Python runtime and removal of `PARLAY_BASE_URL`.
4. Create a new reviewed v2 version/tag through the normal release process. Marketplace agreement acceptance, if needed, is a separate administrator action. Do not claim Marketplace availability before it is actually published.

The public CI workflow is offline. It uses no live sandbox/demo/API calls, data artifacts or API credentials. Its tests exercise mocked HTTP transport and private runner-file handling. No live private-repository run has been performed as part of this change; offline tests do not substitute for that release validation.

This action can reduce accidental publication. It cannot control what an authorized recipient does with a local file, alter existing API contracts or grant redistribution rights. Policy/contract updates and any paid-customer notice period require a separate rollout. MIT licenses the code only.

Technical reference: GitHub's [Get a repository endpoint](https://docs.github.com/en/rest/repos/repos#get-a-repository) provides `full_name`, `private` and `visibility`; [workflow contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts) provide the caller repository, workflow token and runner directories. The action requires the exact returned caller name and private visibility. It does not trust a caller-supplied visibility flag.
