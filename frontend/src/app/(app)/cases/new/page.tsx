'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useMemo, useState, type FormEvent } from 'react';
import type { Map as MapLibreMap } from 'maplibre-gl';
import type { Polygon } from 'geojson';
import { PageHeader } from '@/components/layout/PageHeader';
import { DrawAoiControl } from '@/components/map/DrawAoiControl';
import { MapView, type MapDataLayer } from '@/components/map/MapView';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ErrorState } from '@/components/ui/ErrorState';
import { Input } from '@/components/ui/Input';
import { LinkButton } from '@/components/ui/LinkButton';
import { Textarea } from '@/components/ui/Textarea';
import { useToast } from '@/components/ui/Toast';
import { useCreateCase } from '@/lib/api/hooks';
import { MAX_AOI_KM2, MAX_WINDOW_DAYS } from '@/lib/config';
import {
  localInputToIso,
  polygonBbox,
  validateAoi,
  validateTimeWindow,
  type ValidationIssue,
} from '@/lib/geo';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

function issueFor(issues: ValidationIssue[], field: ValidationIssue['field']): string | undefined {
  return issues.find((issue) => issue.field === field)?.message;
}

/**
 * UI-003 — Create case.
 *
 * The AOI and time-window rules from API.md §4 are checked here before the
 * request is sent, so the analyst is told which corner or which date is the
 * problem instead of receiving a generic 422. The server still validates
 * everything: this is a courtesy, not the boundary.
 */
export default function NewCasePage() {
  const router = useRouter();
  const { toast } = useToast();
  const createCase = useCreateCase();

  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [aoi, setAoi] = useState<Polygon | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const handleMapReady = useCallback((instance: MapLibreMap | null) => setMap(instance), []);

  const issues = useMemo<ValidationIssue[]>(() => {
    const result: ValidationIssue[] = [];
    if (!title.trim()) result.push({ field: 'title', message: 'Give the case a title.' });
    result.push(...validateAoi(aoi));
    result.push(...validateTimeWindow(localInputToIso(startTime), localInputToIso(endTime)));
    return result;
  }, [title, aoi, startTime, endTime]);

  const layers = useMemo<MapDataLayer[]>(
    () =>
      aoi
        ? [
            {
              id: 'aoi',
              kind: 'polygon',
              colorVar: '--map-aoi',
              colorFallback: '#4f8ff7',
              visible: true,
              data: {
                type: 'FeatureCollection',
                features: [{ type: 'Feature', properties: {}, geometry: aoi }],
              },
            },
          ]
        : [],
    [aoi],
  );

  const fitTo = useMemo(() => polygonBbox(aoi), [aoi]);
  const serverFieldErrors = createCase.error?.fieldErrors ?? {};
  const showIssues = submitted;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (issues.length > 0 || !aoi) return;

    createCase.mutate(
      {
        title: title.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        aoi,
        start_time: localInputToIso(startTime),
        end_time: localInputToIso(endTime),
      },
      {
        onSuccess: (created) => {
          toast({
            tone: 'success',
            title: 'Case created',
            description: `“${created.title}” is ready. Run the pipeline to begin the investigation.`,
          });
          router.push(`/cases/${created.id}`);
        },
        onError: (error) => {
          toast({ tone: 'error', title: 'Could not create the case', description: error.message });
        },
      },
    );
  };

  const submitting = createCase.isPending;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="New case"
        subtitle={`Pin an area of interest to a time window. The AOI must be a simple polygon of at most ${MAX_AOI_KM2.toLocaleString('en-US')} km², and the window at most ${MAX_WINDOW_DAYS} days.`}
        actions={
          <LinkButton href="/cases" variant="ghost" size="md">
            Cancel
          </LinkButton>
        }
      />

      <form onSubmit={handleSubmit} noValidate>
        <div className={styles.createGrid}>
          <div className={styles.formStack}>
            <div className={styles.mapPane}>
              <MapView
                label="Area-of-interest drawing map"
                layers={layers}
                fitTo={fitTo}
                onMapReady={handleMapReady}
                hint="Click to place corners; double-click, press Enter, or click the first corner to close the shape. Escape cancels, Backspace removes the last corner. You can also type the bounds below."
              />
            </div>

            <Card
              title="Area of interest"
              description="Draw on the map or enter bounds — both define the same polygon."
            >
              <DrawAoiControl
                map={map}
                value={aoi}
                onChange={setAoi}
                disabled={submitting}
                error={showIssues ? (issueFor(issues, 'aoi') ?? serverFieldErrors['aoi']) : null}
              />
            </Card>
          </div>

          <div className={styles.formStack}>
            <Card title="Case details">
              {createCase.isError && Object.keys(serverFieldErrors).length === 0 ? (
                <div className={styles.formError}>
                  <ErrorState compact error={createCase.error} />
                </div>
              ) : null}

              <div className={styles.formStack}>
                <Input
                  label="Title"
                  required
                  maxLength={200}
                  disabled={submitting}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  error={
                    showIssues ? (issueFor(issues, 'title') ?? serverFieldErrors['title']) : null
                  }
                  hint="Something an analyst will recognise in the case list."
                />
                <Textarea
                  label="Description"
                  optional
                  rows={4}
                  maxLength={2000}
                  disabled={submitting}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  error={serverFieldErrors['description']}
                  hint="Context for whoever reads the evidence report later."
                />
                <Input
                  label="Start time (UTC)"
                  type="datetime-local"
                  required
                  mono
                  disabled={submitting}
                  value={startTime}
                  onChange={(event) => setStartTime(event.target.value)}
                  error={
                    showIssues
                      ? (issueFor(issues, 'start_time') ?? serverFieldErrors['start_time'])
                      : null
                  }
                />
                <Input
                  label="End time (UTC)"
                  type="datetime-local"
                  required
                  mono
                  disabled={submitting}
                  value={endTime}
                  onChange={(event) => setEndTime(event.target.value)}
                  error={
                    showIssues
                      ? (issueFor(issues, 'end_time') ?? serverFieldErrors['end_time'])
                      : null
                  }
                  hint={`Times are interpreted as UTC. Maximum window ${MAX_WINDOW_DAYS} days.`}
                />
              </div>
            </Card>

            <div className={styles.formActions}>
              <LinkButton href="/cases" variant="ghost" size="md">
                Cancel
              </LinkButton>
              <Button
                type="submit"
                variant="primary"
                size="md"
                loading={submitting}
                loadingLabel="Creating case"
                disabled={submitting || (submitted && issues.length > 0)}
              >
                Create case
              </Button>
            </div>

            {showIssues && issues.length > 0 ? (
              <p role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-xs)' }}>
                {issues.length === 1
                  ? 'One field needs attention before the case can be created.'
                  : `${issues.length} fields need attention before the case can be created.`}
              </p>
            ) : null}
          </div>
        </div>
      </form>
    </main>
  );
}
