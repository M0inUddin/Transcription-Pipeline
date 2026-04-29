create extension if not exists pgcrypto;

create table if not exists public.transcription_jobs (
    job_id uuid primary key default gen_random_uuid(),
    status text not null check (status in ('queued', 'processing', 'retrying', 'completed', 'failed')),
    provider text not null default 'deepgram' check (provider in ('deepgram')),
    source_type text not null check (source_type in ('file', 'remote_url', 'base64')),
    source_url text,
    filename text,
    mime_type text,
    size_bytes bigint check (size_bytes is null or size_bytes >= 0),
    duration_seconds double precision check (duration_seconds is null or duration_seconds >= 0),
    audio_path text,
    transcript_path text,
    text text,
    segments jsonb not null default '[]'::jsonb,
    words jsonb not null default '[]'::jsonb,
    detected_language text,
    language_confidence double precision
        constraint transcription_jobs_language_confidence_check
        check (language_confidence is null or (language_confidence >= 0 and language_confidence <= 1)),
    error jsonb,
    retry_count integer not null default 0 check (retry_count >= 0),
    provider_request_id text,
    raw_provider_response jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists transcription_jobs_status_idx
    on public.transcription_jobs (status, created_at);

create index if not exists transcription_jobs_provider_request_id_idx
    on public.transcription_jobs (provider_request_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists transcription_jobs_set_updated_at on public.transcription_jobs;

create trigger transcription_jobs_set_updated_at
before update on public.transcription_jobs
for each row
execute function public.set_updated_at();

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
    (
        'transcription-audio',
        'transcription-audio',
        false,
        26214400,
        array[
            'audio/aac',
            'audio/flac',
            'audio/m4a',
            'audio/mp4',
            'audio/mpeg',
            'audio/mp3',
            'audio/ogg',
            'audio/opus',
            'audio/wav',
            'audio/wave',
            'audio/webm',
            'video/mp4',
            'video/webm',
            'application/ogg'
        ]
    ),
    (
        'transcription-results',
        'transcription-results',
        false,
        26214400,
        array['application/json']
    )
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
