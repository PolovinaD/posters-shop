import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Sparkles, RefreshCw, ImageIcon, CheckCircle, XCircle, Clock } from 'lucide-react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  StatusBadge,
  Loading,
  ErrorMessage,
  EmptyState,
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Input,
  Select,
} from '../components/ui';
import { designsApi } from '../api';
import { cardTitle } from '../lib/studio';

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'queued', label: 'queued' },
  { value: 'generating', label: 'generating' },
  { value: 'ready', label: 'ready' },
  { value: 'failed', label: 'failed' },
];

// Owner-only view of GET /admin/generations: every customer's AI studio generations,
// newest first. The customer filter applies on submit, the status filter immediately;
// both sit in the query key so React Query caches each combination separately and the
// QueryClient's 5 s refetchInterval keeps the queue moving without a manual refresh.
export default function Designs() {
  const [customerDraft, setCustomerDraft] = useState('');
  const [customer, setCustomer] = useState('');
  const [status, setStatus] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['admin-generations', customer, status],
    // empty filters MUST be omitted: an empty `status=` would 422 on the server pattern
    queryFn: () =>
      designsApi.adminGenerations({
        limit: 200,
        ...(customer && { customer }),
        ...(status && { status }),
      }),
  });

  const rows = data ?? [];
  const readyCount = rows.filter((g) => g.status === 'ready').length;
  const failedCount = rows.filter((g) => g.status === 'failed').length;
  const inFlightCount = rows.filter((g) => g.status === 'queued' || g.status === 'generating').length;
  const hasFilters = Boolean(customer || status);

  const applyCustomer = (e) => {
    e.preventDefault();
    setCustomer(customerDraft.trim());
  };

  const clearFilters = () => {
    setCustomerDraft('');
    setCustomer('');
    setStatus('');
  };

  const emptyDescription = hasFilters
    ? `No generations match ${[
        customer && `customer "${customer}"`,
        status && `status "${status}"`,
      ]
        .filter(Boolean)
        .join(' and ')}`
    : 'Generations will appear here as customers use the AI studio';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Designs</h1>
          <p className="text-slate-400">Every customer&apos;s AI studio generations</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="py-4">
          <form onSubmit={applyCustomer} className="flex flex-wrap gap-3 items-end">
            <Input
              label="Customer"
              placeholder="exact e-mail"
              value={customerDraft}
              onChange={(e) => setCustomerDraft(e.target.value)}
              className="w-72"
            />
            <Select
              label="Status"
              options={STATUS_OPTIONS}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-44"
            />
            <Button type="submit">Apply</Button>
            <Button type="button" variant="secondary" onClick={clearFilters}>
              Clear
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Sparkles className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{rows.length}</p>
              <p className="text-sm text-slate-400">Shown</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{readyCount}</p>
              <p className="text-sm text-slate-400">Ready</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-red-500/20 rounded-lg">
              <XCircle className="w-5 h-5 text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{failedCount}</p>
              <p className="text-sm text-slate-400">Failed</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <Clock className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{inFlightCount}</p>
              <p className="text-sm text-slate-400">In flight</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Generations Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5" />
            Generations
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <Loading />
          ) : error ? (
            <ErrorMessage message={error.message} retry={refetch} />
          ) : rows.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>Image</TableHead>
                <TableHead>ID</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Prompt</TableHead>
                <TableHead>Printed</TableHead>
                <TableHead>Bought</TableHead>
                <TableHead>Attempts</TableHead>
                <TableHead>Created</TableHead>
              </TableHeader>
              <TableBody>
                {rows.map((g) => (
                  <TableRow key={g.id}>
                    <TableCell>
                      {g.status === 'ready' && g.image_url ? (
                        <img src={g.image_url} alt="" className="w-12 h-12 object-cover rounded" />
                      ) : (
                        <div className="w-12 h-12 bg-slate-700 rounded flex items-center justify-center">
                          <ImageIcon className="w-6 h-6 text-slate-500" />
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono">#{g.id}</TableCell>
                    <TableCell className="font-mono text-xs">{g.customer_email}</TableCell>
                    <TableCell>
                      <span className="px-2 py-1 bg-slate-700 text-slate-300 rounded text-xs font-mono">
                        {g.provider}
                      </span>
                    </TableCell>
                    <TableCell>
                      {g.status === 'failed' ? (
                        <span title={g.failure_reason || ''}>
                          <StatusBadge status={g.status} />
                        </span>
                      ) : (
                        <StatusBadge status={g.status} />
                      )}
                    </TableCell>
                    <TableCell>
                      <span title={g.prompt}>{cardTitle(g)}</span>
                      {g.personalise && (
                        <span className="ml-2 px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-300">
                          Personalised
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {g.catalog_product_sku ? (
                        <Link to={g.product_url} className="text-blue-400 hover:underline font-mono">
                          {g.catalog_product_sku}
                        </Link>
                      ) : (
                        '-'
                      )}
                    </TableCell>
                    <TableCell className="text-green-400 text-xs">
                      {g.purchased_at ? new Date(g.purchased_at).toLocaleString() : '-'}
                    </TableCell>
                    <TableCell className={`font-mono ${g.attempts > 1 ? 'text-amber-400' : 'text-slate-400'}`}>
                      {g.attempts}
                    </TableCell>
                    <TableCell className="text-slate-400 text-xs">
                      {g.created_at ? new Date(g.created_at).toLocaleString() : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={Sparkles} title="No generations" description={emptyDescription} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
