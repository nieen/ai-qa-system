import { defineConfig, globalIgnores } from "eslint/config"
import coreWebVitals from "eslint-config-next/core-web-vitals"

export default defineConfig([
  ...coreWebVitals,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
])
