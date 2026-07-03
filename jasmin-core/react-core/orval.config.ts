import { defineConfig } from 'orval';

// Read the schema from the committed file rather than a running backend.
// `make generate-api` is now the single canonical flow:
//   1. `make generate-schema` writes ./schema.yml from `manage.py spectacular`
//   2. orval reads that file and regenerates src/shared/api/generated/
//   3. commit both — backend serializer changes show up as a schema.yml
//      diff in PR review, and CI fails on stale schema (see ci.yml).
export default defineConfig({
  jasmin: {
    input: {
      target: './schema.yml',
    },
    output: {
      mode: 'tags-split',
      target: 'src/shared/api/generated',
      schemas: 'src/shared/api/generated/models',
      client: 'react-query',
      mock: false,
      clean: true,
      prettier: false,
      override: {
        mutator: {
          path: 'src/shared/services/api.ts',
          name: 'axiosService',
        },
      },
    },
  },
});