'use client';

import { useParams } from 'next/navigation';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { CaseStory } from '@/components/explain/CaseStory';
import { PageHeader } from '@/components/layout/PageHeader';
import { LinkButton } from '@/components/ui/LinkButton';
import { useCase } from '@/lib/api/hooks';
import layout from '@/components/layout/layout.module.css';

/**
 * "Walkthrough" — the investigation explained in plain language, start to finish.
 *
 * This is the screen to open first, and the one to show someone who has never
 * seen the product. It reads the same endpoints as every other case screen and
 * renders them as a narrative, so nothing here can drift away from what the
 * other tabs say.
 */
export default function CaseWalkthroughPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId ?? '';
  const caseQuery = useCase(caseId);

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow={caseQuery.data ? `Case ${caseQuery.data.case_ref}` : 'Case'}
        title="How this investigation worked"
        subtitle="Every step of the chain in plain language, with the real figure each step produced. Start here."
        actions={
          <LinkButton href={`/cases/${caseId}`} variant="secondary">
            Back to the map
          </LinkButton>
        }
      />
      <CaseSubNav caseId={caseId} />
      <CaseStory caseId={caseId} />
    </main>
  );
}
