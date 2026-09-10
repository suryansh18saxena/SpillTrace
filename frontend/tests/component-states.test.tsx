import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { Table, type Column } from '@/components/ui/Table';
import { ApiError } from '@/lib/api/client';

interface Row {
  id: string;
  title: string;
  area: number;
}

const COLUMNS: Column<Row>[] = [
  { key: 'title', header: 'Case', render: (row) => row.title },
  { key: 'area', header: 'Area', numeric: true, render: (row) => row.area },
];

const ROWS: Row[] = [
  { id: 'c1', title: 'Gulf of Kutch suspected discharge', area: 15_400 },
  { id: 'c2', title: 'Mumbai approach slick', area: 820 },
];

function renderTable(props: Partial<React.ComponentProps<typeof Table<Row>>> = {}) {
  return render(
    <Table
      caption="Investigation cases"
      columns={COLUMNS}
      rows={ROWS}
      getRowKey={(row) => row.id}
      {...props}
    />,
  );
}

/**
 * NFR-012 requires every screen to have loading / empty / error / success /
 * disabled states. `Table` is the component every list screen is built from, so
 * it is the one worth pinning down: if these five hold here, they hold on the
 * case list, the admin tables and the vessel tables.
 */
describe('Table — the five required states', () => {
  it('success: renders the rows and an accessible caption', () => {
    renderTable();

    const table = screen.getByRole('table', { name: 'Investigation cases' });
    expect(table).toBeInTheDocument();
    expect(table).not.toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Gulf of Kutch suspected discharge')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(3); // header + 2 data rows
    expect(screen.queryByTestId('skeleton')).not.toBeInTheDocument();
  });

  it('loading: marks the table busy and shows placeholder rows instead of data', () => {
    renderTable({ rows: [], loading: true, skeletonRows: 4 });

    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    // 4 skeleton rows x 2 columns.
    expect(screen.getAllByTestId('skeleton')).toHaveLength(8);
    expect(screen.queryByText('Gulf of Kutch suspected discharge')).not.toBeInTheDocument();
  });

  it('empty: renders the supplied empty state, not a blank body', () => {
    renderTable({
      rows: [],
      empty: (
        <EmptyState title="No cases yet" description="Create a case to start an investigation." />
      ),
    });

    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('No cases yet')).toBeInTheDocument();
    expect(screen.getByText(/create a case to start an investigation/i)).toBeInTheDocument();
  });

  it('error: replaces the body with an alert that quotes the code and request id', async () => {
    const onRetry = vi.fn();
    const error = new ApiError('A required service is unavailable.', {
      code: 'SERVICE_UNAVAILABLE',
      status: 503,
      requestId: '01JREQUEST',
    });

    renderTable({ rows: [], error: <ErrorState error={error} onRetry={onRetry} /> });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('A required service is unavailable.');
    expect(alert).toHaveTextContent('SERVICE_UNAVAILABLE');
    expect(alert).toHaveTextContent('01JREQUEST');
    // The rows must not be rendered alongside the failure.
    expect(screen.queryByText('Gulf of Kutch suspected discharge')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('error wins over rows that are still cached', () => {
    renderTable({ error: <ErrorState error={new Error('boom')} /> });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('Mumbai approach slick')).not.toBeInTheDocument();
  });
});

describe('Button — disabled and loading states', () => {
  it('disabled: is not clickable and is exposed as disabled', async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Run pipeline
      </Button>,
    );

    const button = screen.getByRole('button', { name: 'Run pipeline' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('loading: announces busy, blocks clicks, and keeps its label in the DOM', async () => {
    const onClick = vi.fn();
    render(
      <Button loading loadingLabel="Starting pipeline" onClick={onClick}>
        Run pipeline
      </Button>,
    );

    const button = screen.getByRole('button', { name: /run pipeline/i });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    expect(screen.getByText('Starting pipeline')).toBeInTheDocument();
    expect(screen.getByTestId('spinner')).toBeInTheDocument();

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('enabled: fires exactly once per click', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Run pipeline</Button>);
    await userEvent.click(screen.getByRole('button', { name: 'Run pipeline' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
