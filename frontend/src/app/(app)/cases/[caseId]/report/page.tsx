'use client';

import { useParams } from 'next/navigation';
import { useMemo, useRef, useState } from 'react';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import { IconDownload, IconPrint, IconRefresh } from '@/components/ui/Icons';
import { useToast } from '@/components/ui/Toast';
import { useArtifacts, useCase, useReportHtml, useReportPdfDownload } from '@/lib/api/hooks';
import type { EvidenceArtifact } from '@/lib/api/types';
import { downloadBlob, downloadText } from '@/lib/download';
import {
  EMPTY_VALUE,
  formatBytes,
  formatDateTimeCompact,
  humanizeIdentifier,
  truncateId,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

/** UI-009 — the rendered evidence report and the artifacts behind it. */
export default function EvidenceReportPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;
  const { toast } = useToast();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [pdfUnavailable, setPdfUnavailable] = useState<string | null>(null);

  const caseQuery = useCase(caseId);
  const reportQuery = useReportHtml(caseId);
  const artifactsQuery = useArtifacts(caseId);
  const pdfDownload = useReportPdfDownload(caseId);

  const artifacts = useMemo(() => artifactsQuery.data?.items ?? [], [artifactsQuery.data]);
  const pdfArtifact = artifacts.find((artifact) => artifact.artifact_type === 'REPORT_PDF');
  const caseRef = caseQuery.data?.case_ref ?? truncateId(caseId, 8, 4);

  const columns: Column<EvidenceArtifact>[] = [
    {
      key: 'type',
      header: 'Artifact',
      render: (row) => (
        <span className={styles.cellPrimary}>
          <span>{row.label ?? humanizeIdentifier(row.artifact_type)}</span>
          <span className={styles.cellSub}>{row.artifact_type}</span>
        </span>
      ),
    },
    {
      key: 'media',
      header: 'Media type',
      mono: true,
      width: '11rem',
      render: (row) => row.media_type ?? EMPTY_VALUE,
    },
    {
      key: 'size',
      header: 'Size',
      numeric: true,
      mono: true,
      width: '7rem',
      render: (row) => formatBytes(row.size_bytes ?? null),
    },
    {
      key: 'checksum',
      header: 'SHA-256',
      mono: true,
      render: (row) => (
        <span title={row.checksum_sha256}>{truncateId(row.checksum_sha256, 12, 8)}</span>
      ),
    },
    {
      key: 'provenance',
      header: 'Data',
      width: '7rem',
      render: (row) => <ProvenanceBadge provenance={row.data_provenance} />,
    },
    {
      key: 'created',
      header: 'Produced',
      mono: true,
      width: '11rem',
      render: (row) => formatDateTimeCompact(row.created_at ?? null),
    },
  ];

  const handlePrint = () => {
    const frame = frameRef.current;
    // The iframe is same-origin (`srcdoc`), so the parent may drive its print
    // dialog. Scripts stay disabled inside it — see the sandbox attribute.
    if (!frame?.contentWindow) {
      toast({
        tone: 'error',
        title: 'Nothing to print',
        description: 'The report has not finished loading yet.',
      });
      return;
    }
    frame.contentWindow.focus();
    frame.contentWindow.print();
  };

  const handleDownloadHtml = () => {
    if (!reportQuery.data) return;
    downloadText(reportQuery.data, `spilltrace-${caseRef}-report.html`, 'text/html');
  };

  const handleDownloadPdf = () => {
    setPdfUnavailable(null);
    pdfDownload.mutate(undefined, {
      onSuccess: (blob) => downloadBlob(blob, `spilltrace-${caseRef}-report.pdf`),
      onError: (error) => {
        // A missing PDF is a normal deployment state, not a failure to report as
        // one: the HTML report above is complete and is the evidence artifact.
        setPdfUnavailable(
          error.isNotFound
            ? 'No PDF export exists for this case. The HTML report above is the complete evidence record; a PDF is only produced when the PDF toolchain is installed and the report stage has run.'
            : error.message,
        );
      },
    });
  };

  if (!caseId) return null;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="Evidence report"
        subtitle={
          caseQuery.data
            ? `The full investigative record for ${caseQuery.data.title}, rendered by the API.`
            : 'The full investigative record for this case, rendered by the API.'
        }
        actions={
          <LinkButton href={`/cases/${caseId}`} variant="secondary" size="md">
            Back to the map
          </LinkButton>
        }
      />
      <CaseSubNav caseId={caseId} />

      <div className={styles.detailStack}>
        <div className={styles.toolbar}>
          <Button
            variant="secondary"
            size="md"
            onClick={handlePrint}
            disabled={!reportQuery.data}
            leadingIcon={<IconPrint size={15} />}
          >
            Print
          </Button>
          <Button
            variant="secondary"
            size="md"
            onClick={handleDownloadHtml}
            disabled={!reportQuery.data}
            leadingIcon={<IconDownload size={15} />}
          >
            Download HTML
          </Button>
          <Button
            variant="secondary"
            size="md"
            onClick={handleDownloadPdf}
            loading={pdfDownload.isPending}
            loadingLabel="Fetching the PDF"
            leadingIcon={<IconDownload size={15} />}
          >
            Download PDF
          </Button>
          {pdfArtifact ? (
            <Badge tone="success" dot>
              PDF export available
            </Badge>
          ) : (
            <Badge tone="neutral" dot title="No REPORT_PDF artifact is recorded for this case.">
              PDF export not recorded
            </Badge>
          )}
          <Button
            variant="ghost"
            size="md"
            onClick={() => void reportQuery.refetch()}
            loading={reportQuery.isFetching}
            loadingLabel="Reloading the report"
            leadingIcon={<IconRefresh size={15} />}
          >
            Reload
          </Button>
        </div>

        {pdfUnavailable ? <Notice tone="info" label="PDF export" text={pdfUnavailable} /> : null}

        <Notice
          text={caseQuery.data?.notice}
          tone={caseQuery.data?.data_provenance === 'SYNTHETIC' ? 'synthetic' : 'caution'}
          label={caseQuery.data?.data_provenance === 'SYNTHETIC' ? 'Synthetic data' : undefined}
        />

        <Card
          title="Report"
          description="Rendered by the API and shown verbatim in an isolated frame — no script from the document can run, and nothing in it is re-interpreted by this application."
          flush
        >
          {reportQuery.isError ? (
            <div style={{ padding: 'var(--space-4)' }}>
              <ErrorState
                error={reportQuery.error}
                title={reportQuery.error?.isNotFound ? 'No report yet' : undefined}
                description={
                  reportQuery.error?.isNotFound
                    ? 'This case has no rendered report. Run the report.build stage once detection, drift and scoring have completed.'
                    : 'The evidence report could not be loaded.'
                }
                onRetry={() => void reportQuery.refetch()}
              />
            </div>
          ) : reportQuery.isPending ? (
            <div style={{ padding: 'var(--space-4)' }} aria-busy="true">
              <span className="sr-only">Loading the evidence report</span>
              <Skeleton height="24rem" radius="var(--radius-md)" />
            </div>
          ) : (
            <iframe
              ref={frameRef}
              title="SPILLTRACE evidence report"
              className={styles.reportFrame}
              // No `allow-scripts`: the document is rendered, never executed.
              // `allow-same-origin` is what lets the Print button reach it, and
              // `allow-modals` is what lets the print dialog open.
              sandbox="allow-same-origin allow-modals"
              srcDoc={reportQuery.data}
            />
          )}
        </Card>

        <Card
          title="Evidence artifacts"
          description="Every file the pipeline produced for this case, with the SHA-256 checksum recorded at the time it was written."
          flush
        >
          <Table
            caption="Evidence artifacts and checksums"
            columns={columns}
            rows={artifacts}
            getRowKey={(row) => row.id}
            loading={artifactsQuery.isPending}
            error={
              artifactsQuery.isError ? (
                <ErrorState
                  compact
                  error={artifactsQuery.error}
                  onRetry={() => void artifactsQuery.refetch()}
                />
              ) : undefined
            }
            empty={
              <EmptyState
                compact
                title="No artifacts yet"
                description="This case has not produced any stored artifact. Artifacts appear as each pipeline stage writes its output."
              />
            }
          />
        </Card>
      </div>
    </main>
  );
}
