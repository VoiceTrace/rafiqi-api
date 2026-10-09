-- Rafiqi schema at ad0717cefe31da9b797e1234d94f887a15fde07a
-- Migration head: 83bcb2215849
-- Reconstructed application DDL only; no seed data or alembic_version state.
-- Use Alembic migrations for deployment; this file is a database-layout reference.

CREATE TABLE review_subjects (
	id VARCHAR(100) NOT NULL,
	title JSON NOT NULL,
	PRIMARY KEY (id)
);


CREATE TABLE schools (
	id UUID NOT NULL,
	name VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
);


CREATE TABLE review_chapters (
	id VARCHAR(100) NOT NULL,
	subject_id VARCHAR(100) NOT NULL,
	title JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(subject_id) REFERENCES review_subjects (id)
);

CREATE INDEX ix_review_chapters_subject_id ON review_chapters (subject_id);

CREATE TABLE users (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	email VARCHAR(255) NOT NULL,
	full_name VARCHAR(255) NOT NULL,
	role VARCHAR(20) NOT NULL,
	hashed_password VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	avatar_url TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	UNIQUE (email)
);

CREATE INDEX ix_users_school_id ON users (school_id);

CREATE TABLE conversations (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversations_school_id ON conversations (school_id);
CREATE INDEX ix_conversations_student_id ON conversations (student_id);

CREATE TABLE mastery_records (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	subject_id VARCHAR(100) NOT NULL,
	concept_ref VARCHAR(100) NOT NULL,
	mastery_score FLOAT NOT NULL,
	mastery_band VARCHAR(20) NOT NULL,
	evidence_count INTEGER NOT NULL,
	attempt_count INTEGER NOT NULL,
	assisted_evidence_count INTEGER NOT NULL,
	dominant_error_type VARCHAR(100),
	calculation_version VARCHAR(20) NOT NULL,
	last_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_mastery_band CHECK (mastery_band IN ('needs_support', 'developing', 'secure')),
	CONSTRAINT ck_mastery_assisted_count CHECK (assisted_evidence_count >= 0 AND assisted_evidence_count <= evidence_count),
	CONSTRAINT ck_mastery_attempt_count CHECK (attempt_count >= evidence_count),
	CONSTRAINT ck_mastery_evidence_count CHECK (evidence_count >= 1),
	CONSTRAINT ck_mastery_score CHECK (mastery_score >= 0 AND mastery_score <= 1),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(subject_id) REFERENCES review_subjects (id),
	CONSTRAINT uq_mastery_student_concept UNIQUE (school_id, student_id, subject_id, concept_ref)
);

CREATE INDEX ix_mastery_records_school_id ON mastery_records (school_id);
CREATE INDEX ix_mastery_records_student_id ON mastery_records (student_id);
CREATE INDEX ix_mastery_records_subject_id ON mastery_records (subject_id);

CREATE TABLE refresh_tokens (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE TABLE review_lessons (
	id VARCHAR(100) NOT NULL,
	content JSON NOT NULL,
	chapter_id VARCHAR(100) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_review_lesson_chapter FOREIGN KEY(chapter_id) REFERENCES review_chapters (id)
);

CREATE INDEX ix_review_lessons_chapter_id ON review_lessons (chapter_id);

CREATE TABLE student_profiles (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE,
	UNIQUE (student_id)
);

CREATE INDEX ix_student_profiles_school_id ON student_profiles (school_id);

CREATE TABLE profile_traits (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	profile_id UUID NOT NULL,
	source_conversation_id UUID,
	category VARCHAR(50) NOT NULL,
	trait_key VARCHAR(100) NOT NULL,
	title VARCHAR(255) NOT NULL,
	description TEXT NOT NULL,
	teaching_tip TEXT,
	score FLOAT DEFAULT '0.0' NOT NULL,
	confidence VARCHAR(20) DEFAULT 'still_forming' NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(profile_id) REFERENCES student_profiles (id) ON DELETE CASCADE,
	FOREIGN KEY(source_conversation_id) REFERENCES conversations (id) ON DELETE SET NULL
);

CREATE INDEX ix_profile_traits_profile_id ON profile_traits (profile_id);
CREATE INDEX ix_profile_traits_school_id ON profile_traits (school_id);

CREATE TABLE review_sessions (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	lesson_id VARCHAR(100) NOT NULL,
	content JSON NOT NULL,
	state JSON NOT NULL,
	version INTEGER DEFAULT '0' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_review_student_lesson UNIQUE (school_id, student_id, lesson_id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(lesson_id) REFERENCES review_lessons (id)
);


CREATE TABLE review_attempts (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	session_id UUID NOT NULL,
	lesson_id VARCHAR(100) NOT NULL,
	request_id UUID NOT NULL,
	question_id VARCHAR(100) NOT NULL,
	concept_ref VARCHAR(100) NOT NULL,
	response_text TEXT NOT NULL,
	option_id VARCHAR(100),
	correctness_score FLOAT NOT NULL,
	error_type VARCHAR(100),
	hint_level INTEGER NOT NULL,
	assisted BOOLEAN NOT NULL,
	attempt_number INTEGER NOT NULL,
	locale VARCHAR(2) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_review_attempt_session_request UNIQUE (session_id, request_id),
	CONSTRAINT ck_review_attempt_score CHECK (correctness_score >= 0 AND correctness_score <= 1),
	CONSTRAINT ck_review_attempt_hint_level CHECK (hint_level >= 0),
	CONSTRAINT ck_review_attempt_number CHECK (attempt_number >= 1),
	CONSTRAINT ck_review_attempt_error_type CHECK (error_type IS NULL OR error_type IN ('force_pair_unequal_magnitude', 'force_pair_missing_reaction', 'force_pair_incomplete_distinct_objects', 'force_pair_missing_distinct_objects', 'balanced_force_means_stopped', 'kinetic_energy_requires_motion', 'equivalent_fraction_denominator_only')),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(session_id) REFERENCES review_sessions (id) ON DELETE CASCADE,
	FOREIGN KEY(lesson_id) REFERENCES review_lessons (id)
);

CREATE INDEX ix_review_attempts_school_id ON review_attempts (school_id);
CREATE INDEX ix_review_attempts_session_id ON review_attempts (session_id);
CREATE INDEX ix_review_attempts_student_id ON review_attempts (student_id);

CREATE TABLE review_session_summaries (
	id UUID NOT NULL,
	school_id UUID NOT NULL,
	student_id UUID NOT NULL,
	session_id UUID NOT NULL,
	lesson_id VARCHAR(100) NOT NULL,
	concepts JSON NOT NULL,
	total_attempts INTEGER NOT NULL,
	calculation_version VARCHAR(20) NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_review_summary_attempts CHECK (total_attempts >= 1),
	FOREIGN KEY(lesson_id) REFERENCES review_lessons (id),
	FOREIGN KEY(school_id) REFERENCES schools (id) ON DELETE CASCADE,
	FOREIGN KEY(session_id) REFERENCES review_sessions (id) ON DELETE CASCADE,
	FOREIGN KEY(student_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT uq_review_summary_session UNIQUE (session_id)
);

CREATE INDEX ix_review_session_summaries_school_id ON review_session_summaries (school_id);
CREATE INDEX ix_review_session_summaries_student_id ON review_session_summaries (student_id);
