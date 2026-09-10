'use client';

import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { MetaList } from '@/components/common/MetaList';
import { formatDateTimeCompact } from '@/lib/format';
import type { RunManifest } from '@/lib/api/types';
import styles from '@/styles/pages.module.css';

export interface RunManifestCardProps {
  manifest?: RunManifest | null;
  title?: string;
  description?: string;
}

/**
 * The reproducibility envelope (NFR-005, AD-6).
 *
 * The named fields get a readable summary; the whole object is then printed
 * verbatim underneath. That second part is the point: an evidence artifact has
 * to be reproducible from what is recorded, and a UI that paraphrases the
 * manifest is a UI that can quietly drop the parameter that mattered.
 */
export function RunManifestCard({
  manifest,
  title = 'Run manifest',
  description = 'Everything needed to reproduce this result: the stage, the provider, the seed and the exact parameters. Printed verbatim — nothing is summarised away.',
}: RunManifestCardProps) {
  if (!manifest) {
    return (
      <Card title={title}>
        <EmptyState
          compact
          title="No run manifest recorded"
          description="This artifact predates manifest capture, or was not produced by a tracked pipeline stage. Without it the result cannot be reproduced exactly."
        />
      </Card>
    );
  }

  return (
    <Card title={title} description={description}>
      <MetaList
        dense
        entries={[
          { key: 'stage', term: 'Stage', value: manifest.stage ?? '—', mono: true },
          { key: 'provider', term: 'Provider', value: manifest.provider ?? '—', mono: true },
          {
            key: 'model',
            term: 'Model',
            mono: true,
            value: manifest.model_name ?? 'Not a model stage',
            hint: manifest.model_version ? `version ${manifest.model_version}` : undefined,
          },
          {
            key: 'seed',
            term: 'Seed',
            mono: true,
            value:
              manifest.seed === null || manifest.seed === undefined ? '—' : String(manifest.seed),
          },
          {
            key: 'software',
            term: 'Software',
            mono: true,
            value: manifest.software_version ?? '—',
            hint: manifest.git_sha && manifest.git_sha !== 'unknown' ? manifest.git_sha : undefined,
          },
          {
            key: 'created',
            term: 'Produced',
            mono: true,
            value: formatDateTimeCompact(manifest.created_at ?? null),
          },
        ]}
      />

      {manifest.notes && manifest.notes.length > 0 ? (
        <ul className={styles.inlineNotices} style={{ marginTop: 'var(--space-3)' }}>
          {manifest.notes.map((note) => (
            <li key={note} className={styles.explanation}>
              {note}
            </li>
          ))}
        </ul>
      ) : null}

      <pre className={styles.manifest} style={{ marginTop: 'var(--space-3)' }}>
        {JSON.stringify(manifest, null, 2)}
      </pre>
    </Card>
  );
}
