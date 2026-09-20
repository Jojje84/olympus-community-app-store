export APP_SPARKYFITNESS_DB_PASSWORD="$(derive_entropy "${app_entropy_identifier}-postgres-password")"
export APP_SPARKYFITNESS_APP_DB_PASSWORD="$(derive_entropy "${app_entropy_identifier}-app-db-password")"
export APP_SPARKYFITNESS_API_ENCRYPTION_KEY="$(derive_entropy "${app_entropy_identifier}-api-encryption-key")"
export APP_SPARKYFITNESS_AUTH_SECRET="$(derive_entropy "${app_entropy_identifier}-better-auth-secret")"
