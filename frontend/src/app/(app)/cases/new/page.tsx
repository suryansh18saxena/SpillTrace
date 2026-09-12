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
import { Select, type SelectOption } from '@/components/ui/Select';
import { Textarea } from '@/components/ui/Textarea';
import { useToast } from '@/components/ui/Toast';
import { useCreateCase, useUploadScene } from '@/lib/api/hooks';
import { MAX_AOI_KM2, MAX_WINDOW_DAYS } from '@/lib/config';
import { formatBytes, formatDuration, formatTimeRange } from '@/lib/format';
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
/**
 * "now" (or an offset from it) as the exact string a `datetime-local` input wants.
 *
 * Built from the UTC parts on purpose: the field is labelled UTC, so what it holds
 * is the UTC instant and never the viewer's local wall clock.
 */
function utcInputValue(offsetMs = 0): string {
  const date = new Date(Date.now() + offsetMs);
  const pad = (value: number) => String(value).padStart(2, '0');
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    `T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  );
}

const HOUR_MS = 3_600_000;

/**
 * One-click windows.
 *
 * The browser's native date field is awkward: it renders in the browser's own
 * locale order (a US-locale Chrome shows mm/dd/yyyy) while this field means UTC,
 * and the calendar only opens from a small glyph at the right-hand edge. These
 * buttons set both ends at once, which is the dependable way to fill this form.
 */
const WINDOW_PRESETS: ReadonlyArray<{ label: string; hours: number }> = [
  { label: 'Last 24 hours', hours: 24 },
  { label: 'Last 7 days', hours: 24 * 7 },
  { label: 'Last 30 days', hours: 24 * 30 },
];

type UnitsChoice = 'auto' | 'db' | 'linear';

/**
 * How the pixel values should be read.
 *
 * This is the one question a supplied file cannot answer for itself. σ0 in dB and
 * σ0 in linear power look identical to a file reader, and reading dB as linear
 * rejects every pixel — the scene comes back empty rather than wrong. Detection
 * from the values is right in every case we have seen, so it leads; the overrides
 * exist for a file whose values are scaled into a range that hides the difference.
 */
const UNIT_OPTIONS: readonly SelectOption[] = [
  { value: 'auto', label: 'Detect from the pixel values (recommended)' },
  { value: 'db', label: 'σ0 already in dB' },
  { value: 'linear', label: 'σ0 in linear power' },
];

export default function NewCasePage() {
  const router = useRouter();
  const { toast } = useToast();
  const createCase = useCreateCase();
  const uploadScene = useUploadScene();

  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [aoi, setAoi] = useState<Polygon | null>(null);
  const [sceneFile, setSceneFile] = useState<File | null>(null);
  const [units, setUnits] = useState<UnitsChoice>('auto');
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

  /**
   * What the two time fields currently mean, written back in one unambiguous line.
   *
   * The native field renders in the browser's locale order, so "08/12" reads as
   * 12 August in a US-locale Chrome and 8 December elsewhere. Echoing the resolved
   * UTC instants removes that ambiguity before the case is created.
   */
  const windowSummary = useMemo(() => {
    const base = `Times are interpreted as UTC. Maximum window ${MAX_WINDOW_DAYS} days.`;
    if (!startTime || !endTime) return base;
    const from = new Date(localInputToIso(startTime));
    const to = new Date(localInputToIso(endTime));
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return base;
    const seconds = (to.getTime() - from.getTime()) / 1000;
    if (seconds <= 0) return `${base} The end time must come after the start time.`;
    return `${base} This window is ${formatTimeRange(
      from.toISOString(),
      to.toISOString(),
    )} — ${formatDuration(seconds)} long.`;
  }, [startTime, endTime]);

  /**
   * What attaching a file changes, said before the analyst commits to it.
   *
   * Without one the case is created empty and waits for a catalogue search; with
   * one the chain starts immediately on the supplied pixels. That is a large
   * difference in what the next screen will be doing, so it is stated here.
   */
  const fileHint = useMemo(() => {
    if (!sceneFile) {
      return 'Single- or dual-band GeoTIFF of σ0 (band 1 is read as VV, band 2 as VH). Leave empty to create the case and search the catalogue instead.';
    }
    return `${sceneFile.name} — ${formatBytes(sceneFile.size)}. Creating the case will attach this file and start detection on it straight away.`;
  }, [sceneFile]);

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
          if (!sceneFile) {
            toast({
              tone: 'success',
              title: 'Case created',
              description: `“${created.title}” is ready. Run the pipeline to begin the investigation.`,
            });
            router.push(`/cases/${created.id}`);
            return;
          }
          uploadScene.mutate(
            { caseId: created.id, file: sceneFile, units, runPipeline: true },
            {
              onSuccess: (scene) => {
                toast({
                  tone: 'success',
                  title: 'Image attached — detection running',
                  description: `${scene.polarizations.join(' and ')} read as σ0 in ${
                    scene.units === 'db' ? 'dB' : 'linear power'
                  }. ${
                    scene.georeferenced
                      ? 'It was placed from its own map reference.'
                      : 'It carries no map reference, so it was placed on the area of interest.'
                  }`,
                });
                router.push(`/cases/${created.id}`);
              },
              onError: (error) => {
                // The case itself was saved; only the image failed. Send the analyst
                // to it rather than stranding them on a form whose work already exists.
                toast({
                  tone: 'error',
                  title: 'Case created, but the image was not attached',
                  description: `${error.message} You can try the upload again from the case.`,
                });
                router.push(`/cases/${created.id}`);
              },
            },
          );
        },
        onError: (error) => {
          toast({ tone: 'error', title: 'Could not create the case', description: error.message });
        },
      },
    );
  };

  const submitting = createCase.isPending || uploadScene.isPending;

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
                <div className={styles.presetRow}>
                  <span className={styles.presetLabel}>Quick window</span>
                  {WINDOW_PRESETS.map((preset) => (
                    <Button
                      key={preset.label}
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={submitting}
                      onClick={() => {
                        setStartTime(utcInputValue(-preset.hours * HOUR_MS));
                        setEndTime(utcInputValue());
                      }}
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
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
                  hint={windowSummary}
                />
              </div>
            </Card>

            <Card
              title="Satellite image"
              description="Optional. Attach a SAR measurement file you already hold and the investigation runs on it directly — no catalogue search, no download."
            >
              <div className={styles.formStack}>
                <Input
                  label="Measurement file"
                  type="file"
                  accept=".tif,.tiff,image/tiff"
                  disabled={submitting}
                  onChange={(event) => setSceneFile(event.target.files?.[0] ?? null)}
                  hint={fileHint}
                />
                <Select
                  label="Pixel units"
                  options={UNIT_OPTIONS}
                  value={units}
                  disabled={submitting || !sceneFile}
                  onChange={(event) => setUnits(event.target.value as UnitsChoice)}
                  hint="Catalogue products carry σ0 as linear power; several public training sets publish it in dB. The two are indistinguishable to a file reader, and reading dB as linear finds nothing at all, so leave this on detect unless you know the file disagrees."
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
                loadingLabel={uploadScene.isPending ? 'Attaching image' : 'Creating case'}
                disabled={submitting || (submitted && issues.length > 0)}
              >
                {sceneFile ? 'Create case and detect' : 'Create case'}
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
