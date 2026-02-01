import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Truck, RefreshCw, Package, MapPin, CheckCircle } from 'lucide-react';
import { 
  Card, 
  CardHeader, 
  CardTitle, 
  CardContent, 
  Button,
  Loading, 
  ErrorMessage,
  EmptyState,
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  StatusBadge
} from '../components/ui';
import { logisticsApi } from '../api';

const SHIPMENT_STATUSES = ['pending', 'dispatched', 'in_transit', 'delivered'];

export default function Logistics() {
  const queryClient = useQueryClient();
  
  const { data: shipments, isLoading, error, refetch } = useQuery({
    queryKey: ['shipments'],
    queryFn: logisticsApi.getShipments,
  });
  
  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }) => logisticsApi.updateShipmentStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries(['shipments']);
    },
  });
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  const pendingShipments = shipments?.filter(s => s.status === 'pending') || [];
  const dispatchedShipments = shipments?.filter(s => s.status === 'dispatched') || [];
  const inTransitShipments = shipments?.filter(s => s.status === 'in_transit') || [];
  const deliveredShipments = shipments?.filter(s => s.status === 'delivered') || [];
  
  const getNextStatus = (current) => {
    const idx = SHIPMENT_STATUSES.indexOf(current);
    return idx < SHIPMENT_STATUSES.length - 1 ? SHIPMENT_STATUSES[idx + 1] : null;
  };
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Logistics</h1>
          <p className="text-slate-400">Track shipments and deliveries</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>
      
      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <Package className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{pendingShipments.length}</p>
              <p className="text-sm text-slate-400">Pending</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <Truck className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{dispatchedShipments.length}</p>
              <p className="text-sm text-slate-400">Dispatched</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-purple-500/20 rounded-lg">
              <MapPin className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{inTransitShipments.length}</p>
              <p className="text-sm text-slate-400">In Transit</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{deliveredShipments.length}</p>
              <p className="text-sm text-slate-400">Delivered</p>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Shipments Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Truck className="w-5 h-5" />
            All Shipments
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {shipments && shipments.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>Shipment ID</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Tracking</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead></TableHead>
              </TableHeader>
              <TableBody>
                {shipments.map((shipment) => {
                  const nextStatus = getNextStatus(shipment.status);
                  return (
                    <TableRow key={shipment.id}>
                      <TableCell className="font-mono">#{shipment.id}</TableCell>
                      <TableCell className="font-mono">#{shipment.order_id}</TableCell>
                      <TableCell className="font-mono text-blue-400">
                        {shipment.tracking || '-'}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={shipment.status} />
                      </TableCell>
                      <TableCell className="text-slate-400">
                        {new Date(shipment.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        {nextStatus && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => updateStatusMutation.mutate({
                              id: shipment.id,
                              status: nextStatus
                            })}
                            loading={updateStatusMutation.isPending}
                          >
                            → {nextStatus}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={Truck}
              title="No shipments"
              description="Shipments will appear when orders are produced"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

