# Public Release (Open-Source Mirror)

`pybrid` development happens on anabrid's internal GitLab server, but a
public snapshot of the source tree is mirrored to
[github.com/anabrid/pybrid-computing](https://github.com/anabrid/pybrid-computing)
on every tagged release. The mirror is one-way (GitLab to GitHub) and is
driven by the `publish:github` job in `.gitlab-ci.yml`. This page explains
how that pipeline is structured and how to maintain the `public` branch
that backs it.

## Why a `public` branch?

The internal tree contains a `proto/` git submodule that points at an
internal GitLab URL, which is unreachable for external users. The public
mirror must therefore ship a different `.gitmodules` whose `proto/` entry
points at [github.com/anabrid/analog-protobuf](https://github.com/anabrid/analog-protobuf).
We carry that rewrite as a dedicated branch:

- `main` (internal): canonical source, points the submodule at the
internal GitLab.
- `public` (internal): exactly `main` plus one commit that rewrites
`submodule.proto.url` in `.gitmodules`. Always one commit ahead of
`main`, never more.
- GitHub `main`: a mirror of `public` after rebase, pushed by CI.

!!! info "Why not rewrite history?"
    Carrying a single, mechanical commit on a long-lived branch keeps the
    publishing pipeline simple and lets CI fail loudly the moment someone
    edits `.gitmodules` on `main` (the rebase will conflict, which is the
    correct signal that the rewrite commit needs a human review).

## The `publish:github` CI job

Defined in `.gitlab-ci.yml`. Runs manually or automatically on any tag
pushed to GitLab. Steps:

- Fetch all branches and tags from GitLab (`GIT_DEPTH: 0` is set globally,
so the runner has full history).
- Check out the internal `public` branch and rebase it onto the current
`origin/main`. This replays the single submodule-URL commit on top of
the latest source.
```bash
git checkout -B public origin/public
git rebase origin/main
```
- Force-push the rebased branch to GitHub as `main`.
```bash
git push --force github HEAD:main
```
- Push release tags. Two patterns cover the current tag conventions:
`vX.Y.Z` (used since `v0.11.2`) and bare `X.Y.Z` (older releases).
The legacy `before-actual-implementation` tag is intentionally excluded.
```bash
git push github 'refs/tags/v*:refs/tags/v*'
git push github 'refs/tags/[0-9]*:refs/tags/[0-9]*'
```

The job reuses `GITHUB_TOKEN` and `GITHUB_PAGES_REPO` from the existing
`publish:github-pages` job, so no new CI variables are required. It does
**not** push the rebased branch back to GitLab; the internal `public`
branch is treated as a template that only needs touching when the
rewrite commit itself changes.

!!! info "Tags survive the rebase"
    Rebasing `public` only rewrites the URL commit at the tip. The
    underlying `main` commits keep their SHAs, so every release tag points
    at a commit that ends up in GitHub's history once `public` is pushed.

## The `proto/` submodule itself

The submodule SHA recorded in a parent pybrid commit must be reachable on
public `analog-protobuf`, not just on internal `redac-protobuf`. Two
implications:

- Never bump pybrid's submodule pointer to a `redac-protobuf` feature
branch SHA. Only point at commits that are merged into protobuf's
`main`, since `main` is what gets mirrored to public.
- Internal `redac-protobuf` and public `analog-protobuf` must be kept in
sync. They share `main` SHAs today, but there is no CI keeping them
that way; setting up the same mirror pattern on `redac-protobuf` is
recommended follow-up work.

## Maintaining the `public` branch

The branch should always look like `main` plus exactly one commit that
sets `proto/`'s URL to the public address. To (re)create it from scratch:

```bash
git fetch origin
git checkout -B public origin/main
git config --file .gitmodules \
    submodule.proto.url git@github.com:anabrid/analog-protobuf.git
git add .gitmodules
git commit -m "Public release: rewrite proto/ submodule URL"
git push --force-with-lease origin public
```

When the rebase in CI fails (someone changed `.gitmodules` on `main`),
resolve it locally with the commands above and force-push the new
`public` branch. The job will succeed on the next run.

## What is _not_ mirrored

- `gh-pages` on GitHub is owned by `publish:github-pages` (the docs build)
and is left untouched by `publish:github`.
- Internal-only tags (e.g. `before-actual-implementation`) are excluded
by the tag refspecs above. New internal-only tags must not match the
`v*` or `[0-9]*` patterns, or they will leak.
- Branches other than `main` on GitHub are not maintained. The
previously-published `public` branch on GitHub can be deleted; we
publish to `main` only.
