// GENERATO AUTOMATICAMENTE - non modificare a mano.
//
// Sorgente: worker/jobboard/models/  ->  rigenerare con:  jobboard gen-web-schema
// Lo schema del database e' definito dai modelli SQLAlchemy e applicato con
// Alembic. Questo file esiste solo per dare i tipi al lato TypeScript.

import {
  bigint,
  boolean,
  customType,
  doublePrecision,
  integer,
  jsonb,
  pgTable,
  serial,
  smallint,
  text,
  timestamp,
  varchar,
} from "drizzle-orm/pg-core";

// drizzle-orm non ha un tipo bytea nativo. Qui ci finiscono gli embedding,
// serializzati con numpy.tobytes(): il lato web non li legge mai, ma la colonna
// deve esistere perche' i tipi corrispondano alla tabella reale.
const bytea = customType<{ data: Buffer; driverData: Buffer }>({
  dataType: () => "bytea",
});


// Valori ammessi, gli stessi imposti dai vincoli CHECK nel database.
export type ApplicationEventType = "created" | "cv_generated" | "approved" | "prepared" | "prepare_failed" | "submitted" | "submit_failed" | "email_received" | "status_changed" | "follow_up_due";
export type ApplicationStatus = "draft" | "cv_ready" | "approved" | "needs_human" | "submitted" | "failed" | "withdrawn" | "acknowledged" | "interview" | "rejected" | "offer";
export type ApplicationTier = "a_auto" | "b_assisted" | "c_manual";
export type AtsType = "greenhouse" | "lever" | "ashby" | "workable" | "recruitee" | "smartrecruiters" | "workday" | "taleo" | "other" | "unknown";
export type ContractType = "permanent" | "fixed_term" | "contract" | "internship" | "apprenticeship" | "part_time" | "unknown";
export type LlmUsagePurpose = "match_scoring" | "cv_structure" | "cv_tailor" | "email_classify";
export type MatchStatus = "new" | "seen" | "shortlist" | "hidden" | "applied";
export type RunStatus = "running" | "ok" | "partial" | "failed";
export type SalaryPeriod = "hourly" | "daily" | "monthly" | "yearly";
export type Seniority = "intern" | "junior" | "mid" | "senior" | "lead" | "principal" | "unknown";
export type TaskStatus = "pending" | "running" | "done" | "failed" | "cancelled";
export type TaskType = "run_pipeline" | "generate_cv" | "apply" | "reparse_profile" | "check_email";
export type WorkMode = "on_site" | "hybrid" | "remote" | "unknown";

export const applicantInfo = pgTable("applicant_info", {
  id: serial("id").primaryKey(),
  items: jsonb("items").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type ApplicantInfoRow = typeof applicantInfo.$inferSelect;
export type NewApplicantInfo = typeof applicantInfo.$inferInsert;

export const candidateProfile = pgTable("candidate_profile", {
  id: serial("id").primaryKey(),
  fullName: varchar("full_name", { length: 200 }).notNull(),
  email: varchar("email", { length: 320 }).notNull(),
  phone: varchar("phone", { length: 40 }),
  city: varchar("city", { length: 120 }),
  country: varchar("country", { length: 2 }),
  linkedinUrl: varchar("linkedin_url", { length: 512 }),
  githubUrl: varchar("github_url", { length: 512 }),
  portfolioUrl: varchar("portfolio_url", { length: 512 }),
  workAuthorization: jsonb("work_authorization").notNull(),
  willingToRelocate: boolean("willing_to_relocate").notNull().default(false),
  noticePeriodDays: integer("notice_period_days"),
  salaryExpectationMin: integer("salary_expectation_min"),
  salaryExpectationMax: integer("salary_expectation_max"),
  salaryCurrency: varchar("salary_currency", { length: 3 }).notNull().default("EUR"),
  languages: jsonb("languages").notNull(),
  atsAnswers: jsonb("ats_answers").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type CandidateProfileRow = typeof candidateProfile.$inferSelect;
export type NewCandidateProfile = typeof candidateProfile.$inferInsert;

export const job = pgTable("job", {
  id: serial("id").primaryKey(),
  title: varchar("title", { length: 400 }).notNull(),
  company: varchar("company", { length: 300 }).notNull(),
  companyNormalized: varchar("company_normalized", { length: 300 }).notNull(),
  canonicalKey: varchar("canonical_key", { length: 600 }).notNull(),
  simhash: bigint("simhash", { mode: "number" }),
  contentHash: varchar("content_hash", { length: 64 }).notNull(),
  locationRaw: varchar("location_raw", { length: 400 }),
  city: varchar("city", { length: 160 }),
  region: varchar("region", { length: 160 }),
  country: varchar("country", { length: 2 }),
  workMode: varchar("work_mode", { length: 32 }).$type<WorkMode>().notNull().default("unknown"),
  salaryIsStated: boolean("salary_is_stated").notNull().default(false),
  salaryMin: integer("salary_min"),
  salaryMax: integer("salary_max"),
  salaryCurrency: varchar("salary_currency", { length: 3 }),
  salaryPeriod: varchar("salary_period", { length: 32 }).$type<SalaryPeriod>(),
  salaryEurYearMin: integer("salary_eur_year_min"),
  salaryEurYearMax: integer("salary_eur_year_max"),
  contractType: varchar("contract_type", { length: 32 }).$type<ContractType>().notNull().default("unknown"),
  seniority: varchar("seniority", { length: 32 }).$type<Seniority>().notNull().default("unknown"),
  jobFamily: varchar("job_family", { length: 120 }),
  descriptionRaw: text("description_raw"),
  descriptionClean: text("description_clean").notNull(),
  lang: varchar("lang", { length: 5 }),
  url: varchar("url", { length: 1024 }).notNull(),
  applyUrl: varchar("apply_url", { length: 1024 }),
  atsType: varchar("ats_type", { length: 32 }).$type<AtsType>().notNull().default("unknown"),
  atsBoardToken: varchar("ats_board_token", { length: 200 }),
  atsJobId: varchar("ats_job_id", { length: 200 }),
  postedAt: timestamp("posted_at", { withTimezone: true, mode: "date" }),
  firstSeenAt: timestamp("first_seen_at", { withTimezone: true, mode: "date" }).notNull(),
  lastSeenAt: timestamp("last_seen_at", { withTimezone: true, mode: "date" }).notNull(),
  isActive: boolean("is_active").notNull().default(true),
  embedding: bytea("embedding"),
  embeddingModel: varchar("embedding_model", { length: 128 }),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type JobRow = typeof job.$inferSelect;
export type NewJob = typeof job.$inferInsert;

export const llmUsageLog = pgTable("llm_usage_log", {
  id: serial("id").primaryKey(),
  occurredAt: timestamp("occurred_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  purpose: varchar("purpose", { length: 32 }).$type<LlmUsagePurpose>().notNull(),
  model: varchar("model", { length: 64 }).notNull(),
  calls: integer("calls").notNull().default(1),
  inputTokens: integer("input_tokens").notNull().default(0),
  outputTokens: integer("output_tokens").notNull().default(0),
  referenceId: integer("reference_id"),
  batchId: varchar("batch_id", { length: 36 }),
});
export type LlmUsageLogRow = typeof llmUsageLog.$inferSelect;
export type NewLlmUsageLog = typeof llmUsageLog.$inferInsert;

export const profile = pgTable("profile", {
  id: serial("id").primaryKey(),
  masterProfile: jsonb("master_profile").notNull(),
  rawText: text("raw_text").notNull(),
  sourceFileName: varchar("source_file_name", { length: 255 }).notNull(),
  sourceStoragePath: varchar("source_storage_path", { length: 512 }),
  embedding: bytea("embedding"),
  embeddingModel: varchar("embedding_model", { length: 128 }),
  embeddingDim: integer("embedding_dim"),
  reviewed: boolean("reviewed").notNull().default(false),
  reviewedAt: timestamp("reviewed_at", { withTimezone: true, mode: "date" }),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type ProfileRow = typeof profile.$inferSelect;
export type NewProfile = typeof profile.$inferInsert;

export const settings = pgTable("settings", {
  key: varchar("key", { length: 64 }).primaryKey(),
  value: jsonb("value").notNull(),
  description: varchar("description", { length: 300 }),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type SettingsRow = typeof settings.$inferSelect;
export type NewSettings = typeof settings.$inferInsert;

export const source = pgTable("source", {
  id: serial("id").primaryKey(),
  adapter: varchar("adapter", { length: 64 }).notNull(),
  displayName: varchar("display_name", { length: 128 }).notNull(),
  enabled: boolean("enabled").notNull().default(true),
  config: jsonb("config").notNull(),
  rateLimitPerMin: integer("rate_limit_per_min").notNull().default(30),
  dailyCallBudget: integer("daily_call_budget"),
  lastRunAt: timestamp("last_run_at", { withTimezone: true, mode: "date" }),
  lastError: text("last_error"),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type SourceRow = typeof source.$inferSelect;
export type NewSource = typeof source.$inferInsert;

export const task = pgTable("task", {
  id: serial("id").primaryKey(),
  taskType: varchar("task_type", { length: 32 }).$type<TaskType>().notNull(),
  status: varchar("status", { length: 32 }).$type<TaskStatus>().notNull().default("pending"),
  payload: jsonb("payload").notNull(),
  progress: smallint("progress").notNull().default(0),
  progressMessage: varchar("progress_message", { length: 300 }),
  result: jsonb("result"),
  error: text("error"),
  claimedAt: timestamp("claimed_at", { withTimezone: true, mode: "date" }),
  finishedAt: timestamp("finished_at", { withTimezone: true, mode: "date" }),
  attempts: smallint("attempts").notNull().default(0),
  maxAttempts: smallint("max_attempts").notNull().default(3),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type TaskRow = typeof task.$inferSelect;
export type NewTask = typeof task.$inferInsert;

export const workerHeartbeat = pgTable("worker_heartbeat", {
  id: serial("id").primaryKey(),
  lastSeenAt: timestamp("last_seen_at", { withTimezone: true, mode: "date" }).notNull(),
  version: varchar("version", { length: 32 }),
  hostname: varchar("hostname", { length: 128 }),
  lastRunAt: timestamp("last_run_at", { withTimezone: true, mode: "date" }),
  lastRunStatus: varchar("last_run_status", { length: 32 }).$type<RunStatus>(),
});
export type WorkerHeartbeatRow = typeof workerHeartbeat.$inferSelect;
export type NewWorkerHeartbeat = typeof workerHeartbeat.$inferInsert;

export const jobRequirements = pgTable("job_requirements", {
  id: serial("id").primaryKey(),
  jobId: integer("job_id").notNull(),
  mustHave: text("must_have").array().notNull(),
  niceToHave: text("nice_to_have").array().notNull(),
  techStack: text("tech_stack").array().notNull(),
  minYearsExperience: integer("min_years_experience"),
  maxYearsExperience: integer("max_years_experience"),
  languagesRequired: jsonb("languages_required").notNull(),
  remotePolicy: varchar("remote_policy", { length: 300 }),
  requiresWorkAuthorization: boolean("requires_work_authorization"),
  redFlags: text("red_flags").array().notNull(),
  extractedWith: varchar("extracted_with", { length: 128 }).notNull(),
  extractedAt: timestamp("extracted_at", { withTimezone: true, mode: "date" }).notNull(),
});
export type JobRequirementsRow = typeof jobRequirements.$inferSelect;
export type NewJobRequirements = typeof jobRequirements.$inferInsert;

export const jobSourceLink = pgTable("job_source_link", {
  id: serial("id").primaryKey(),
  jobId: integer("job_id").notNull(),
  sourceId: integer("source_id").notNull(),
  externalId: varchar("external_id", { length: 300 }).notNull(),
  url: varchar("url", { length: 1024 }).notNull(),
  fetchedAt: timestamp("fetched_at", { withTimezone: true, mode: "date" }).notNull(),
  publisher: varchar("publisher", { length: 120 }),
  raw: jsonb("raw"),
});
export type JobSourceLinkRow = typeof jobSourceLink.$inferSelect;
export type NewJobSourceLink = typeof jobSourceLink.$inferInsert;

export const match = pgTable("match", {
  id: serial("id").primaryKey(),
  jobId: integer("job_id").notNull(),
  semanticScore: doublePrecision("semantic_score"),
  keywordScore: doublePrecision("keyword_score"),
  hybridScore: doublePrecision("hybrid_score"),
  score: smallint("score"),
  subscores: jsonb("subscores"),
  rationale: text("rationale"),
  gaps: text("gaps").array().notNull(),
  scoredWith: varchar("scored_with", { length: 128 }),
  scoredAt: timestamp("scored_at", { withTimezone: true, mode: "date" }),
  reachedStage: smallint("reached_stage").notNull().default(0),
  filteredReason: varchar("filtered_reason", { length: 200 }),
  status: varchar("status", { length: 32 }).$type<MatchStatus>().notNull().default("new"),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type MatchRow = typeof match.$inferSelect;
export type NewMatch = typeof match.$inferInsert;

export const run = pgTable("run", {
  id: serial("id").primaryKey(),
  batchId: varchar("batch_id", { length: 36 }).notNull(),
  sourceId: integer("source_id"),
  status: varchar("status", { length: 32 }).$type<RunStatus>().notNull(),
  startedAt: timestamp("started_at", { withTimezone: true, mode: "date" }).notNull(),
  finishedAt: timestamp("finished_at", { withTimezone: true, mode: "date" }),
  jobsFetched: integer("jobs_fetched").notNull().default(0),
  jobsNew: integer("jobs_new").notNull().default(0),
  jobsDuplicate: integer("jobs_duplicate").notNull().default(0),
  apiCalls: integer("api_calls").notNull().default(0),
  error: text("error"),
});
export type RunRow = typeof run.$inferSelect;
export type NewRun = typeof run.$inferInsert;

export const application = pgTable("application", {
  id: serial("id").primaryKey(),
  matchId: integer("match_id").notNull(),
  tier: varchar("tier", { length: 32 }).$type<ApplicationTier>().notNull(),
  status: varchar("status", { length: 32 }).$type<ApplicationStatus>().notNull().default("draft"),
  cvStoragePath: varchar("cv_storage_path", { length: 512 }),
  coverLetterStoragePath: varchar("cover_letter_storage_path", { length: 512 }),
  cvPayload: jsonb("cv_payload"),
  cvLanguage: varchar("cv_language", { length: 5 }),
  cvFitIterations: integer("cv_fit_iterations"),
  submittedAt: timestamp("submitted_at", { withTimezone: true, mode: "date" }),
  wasDryRun: boolean("was_dry_run").notNull().default(false),
  atsResponse: jsonb("ats_response"),
  error: text("error"),
  screenshots: text("screenshots").array().notNull(),
  followUpDueAt: timestamp("follow_up_due_at", { withTimezone: true, mode: "date" }),
  lastEmailCheckedAt: timestamp("last_email_checked_at", { withTimezone: true, mode: "date" }),
  createdAt: timestamp("created_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true, mode: "date" }).notNull().defaultNow(),
});
export type ApplicationRow = typeof application.$inferSelect;
export type NewApplication = typeof application.$inferInsert;

export const applicationEvent = pgTable("application_event", {
  id: serial("id").primaryKey(),
  applicationId: integer("application_id").notNull(),
  eventType: varchar("event_type", { length: 32 }).$type<ApplicationEventType>().notNull(),
  occurredAt: timestamp("occurred_at", { withTimezone: true, mode: "date" }).notNull(),
  note: text("note"),
  payload: jsonb("payload"),
});
export type ApplicationEventRow = typeof applicationEvent.$inferSelect;
export type NewApplicationEvent = typeof applicationEvent.$inferInsert;
