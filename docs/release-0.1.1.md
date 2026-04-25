# Release 0.1.1

`0.1.1` is the first naming-stabilization release for the formal Hermes memory
plugin line.

## Highlights

- repo name is now `lancedb-pro-hermes-plugin`
- plugin provider name stays `hermes_lancedb`
- intended install target for new Hermes machines is now explicit
- migration-oriented imports can preserve original `timestamp` and metadata

## Recommended use

Use this repo when:

- you are installing long-term memory on a fresh Hermes machine
- you want the formal `hermes_lancedb` provider
- you want bootstrap and migration docs to point to one stable install target

## Relationship to bootstrap

For full-machine setup, use:

- [sscomp/hermes-portable-bootstrap](https://github.com/sscomp/hermes-portable-bootstrap)

For the memory plugin itself, use:

- [sscomp/lancedb-pro-hermes-plugin](https://github.com/sscomp/lancedb-pro-hermes-plugin)

## Upgrade note

If you were previously thinking in terms of `hermes-lancedb-plugin`, move to the
new repo name. The provider inside Hermes remains:

```yaml
memory:
  provider: hermes_lancedb
```
