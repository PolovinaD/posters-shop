import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  ShoppingCart, 
  RefreshCw, 
  CreditCard, 
  XCircle, 
  Factory, 
  Truck, 
  CheckCircle,
  ChevronRight,
  Clock
} from 'lucide-react';
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
  StatusBadge,
  Modal
} from '../components/ui';
import { ordersApi } from '../api';

// State machine visualization
const STATE_FLOW = [
  { status: 'created', label: 'Created', icon: Clock },
  { status: 'reserved', label: 'Reserved', icon: Clock },
  { status: 'paid', label: 'Paid', icon: CreditCard },
  { status: 'producing', label: 'Producing', icon: Factory },
  { status: 'shipped', label: 'Shipped', icon: Truck },
  { status: 'delivered', label: 'Delivered', icon: CheckCircle },
];

function OrderStateFlow({ currentStatus }) {
  const currentIndex = STATE_FLOW.findIndex(s => s.status === currentStatus);
  const isCancelled = currentStatus === 'cancelled';
  const isFailed = currentStatus === 'failed';
  
  if (isCancelled || isFailed) {
    return (
      <div className="flex items-center gap-2 text-red-400">
        <XCircle className="w-5 h-5" />
        <span className="font-medium">{currentStatus}</span>
      </div>
    );
  }
  
  return (
    <div className="flex items-center gap-1 overflow-x-auto py-2">
      {STATE_FLOW.map((state, index) => {
        const Icon = state.icon;
        const isPast = index < currentIndex;
        const isCurrent = index === currentIndex;
        const isFuture = index > currentIndex;
        
        return (
          <div key={state.status} className="flex items-center">
            <div className={`
              flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium
              ${isCurrent ? 'bg-blue-500/20 text-blue-400 ring-1 ring-blue-500' :
                isPast ? 'bg-green-500/20 text-green-400' :
                'bg-slate-700/50 text-slate-500'}
            `}>
              <Icon className="w-3.5 h-3.5" />
              {state.label}
            </div>
            {index < STATE_FLOW.length - 1 && (
              <ChevronRight className={`w-4 h-4 mx-0.5 ${
                isPast ? 'text-green-500' : 'text-slate-600'
              }`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function OrderDetailModal({ open, onClose, orderId }) {
  const queryClient = useQueryClient();
  
  const { data: order, isLoading } = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => ordersApi.getOrder(orderId),
    enabled: !!orderId,
  });
  
  const payMutation = useMutation({
    mutationFn: () => ordersApi.payOrder(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['orders']);
      queryClient.invalidateQueries(['order', orderId]);
      queryClient.invalidateQueries(['orderStats']);
    },
  });
  
  const cancelMutation = useMutation({
    mutationFn: () => ordersApi.cancelOrder(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['orders']);
      queryClient.invalidateQueries(['order', orderId]);
      queryClient.invalidateQueries(['orderStats']);
    },
  });
  
  const produceMutation = useMutation({
    mutationFn: () => ordersApi.startProduction(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['orders']);
      queryClient.invalidateQueries(['order', orderId]);
    },
  });
  
  const shipMutation = useMutation({
    mutationFn: () => ordersApi.shipOrder(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['orders']);
      queryClient.invalidateQueries(['order', orderId]);
    },
  });
  
  const deliverMutation = useMutation({
    mutationFn: () => ordersApi.deliverOrder(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries(['orders']);
      queryClient.invalidateQueries(['order', orderId]);
    },
  });
  
  if (!orderId) return null;
  
  return (
    <Modal open={open} onClose={onClose} title={`Order #${orderId}`}>
      {isLoading ? (
        <Loading />
      ) : order ? (
        <div className="space-y-6">
          {/* State Flow */}
          <div>
            <p className="text-sm text-slate-400 mb-2">Order Progress</p>
            <OrderStateFlow currentStatus={order.status} />
          </div>
          
          {/* Order Info */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-slate-400">Customer</p>
              <p className="font-medium">{order.customer_email}</p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Total</p>
              <p className="font-mono text-xl font-bold">${order.total_amount}</p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Created</p>
              <p className="text-sm">{new Date(order.created_at).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Status</p>
              <StatusBadge status={order.status} />
            </div>
          </div>
          
          {/* Items */}
          <div>
            <p className="text-sm text-slate-400 mb-2">Items</p>
            <div className="bg-slate-800 rounded-lg divide-y divide-slate-700">
              {order.items?.map((item, i) => (
                <div key={i} className="flex justify-between items-center p-3">
                  <div>
                    <p className="font-medium">{item.name}</p>
                    <p className="text-sm text-slate-400 font-mono">{item.sku}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono">${item.unit_price}</p>
                    <p className="text-sm text-slate-400">×{item.quantity}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          
          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-4 border-t border-slate-700">
            {order.status === 'reserved' && (
              <>
                <Button 
                  onClick={() => payMutation.mutate()}
                  loading={payMutation.isPending}
                >
                  <CreditCard className="w-4 h-4" />
                  Mark as Paid
                </Button>
                <Button 
                  variant="danger"
                  onClick={() => cancelMutation.mutate()}
                  loading={cancelMutation.isPending}
                >
                  <XCircle className="w-4 h-4" />
                  Cancel Order
                </Button>
              </>
            )}
            {order.status === 'paid' && (
              <>
                <Button 
                  onClick={() => produceMutation.mutate()}
                  loading={produceMutation.isPending}
                >
                  <Factory className="w-4 h-4" />
                  Start Production
                </Button>
                <Button 
                  variant="danger"
                  onClick={() => cancelMutation.mutate()}
                  loading={cancelMutation.isPending}
                >
                  Cancel Order
                </Button>
              </>
            )}
            {order.status === 'producing' && (
              <Button 
                onClick={() => shipMutation.mutate()}
                loading={shipMutation.isPending}
              >
                <Truck className="w-4 h-4" />
                Mark as Shipped
              </Button>
            )}
            {order.status === 'shipped' && (
              <Button 
                variant="success"
                onClick={() => deliverMutation.mutate()}
                loading={deliverMutation.isPending}
              >
                <CheckCircle className="w-4 h-4" />
                Mark as Delivered
              </Button>
            )}
          </div>
          
          {/* Error display */}
          {(payMutation.error || cancelMutation.error) && (
            <p className="text-red-400 text-sm">
              {payMutation.error?.message || cancelMutation.error?.message}
            </p>
          )}
        </div>
      ) : (
        <p className="text-slate-400">Order not found</p>
      )}
    </Modal>
  );
}

export default function Orders() {
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  
  const { data: orders, isLoading, error, refetch } = useQuery({
    queryKey: ['orders', statusFilter],
    queryFn: () => ordersApi.getOrders(statusFilter ? { status: statusFilter } : {}),
  });
  
  const { data: stats } = useQuery({
    queryKey: ['orderStats'],
    queryFn: ordersApi.getOrderStats,
  });
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-slate-400">Manage customer orders and their lifecycle</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>
      
      {/* Status Filter Pills */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setStatusFilter('')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            !statusFilter 
              ? 'bg-blue-500 text-white' 
              : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
          }`}
        >
          All ({Object.values(stats || {}).reduce((a, b) => a + b, 0)})
        </button>
        {['reserved', 'paid', 'producing', 'shipped', 'delivered', 'cancelled'].map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === status 
                ? 'bg-blue-500 text-white' 
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            {status} ({stats?.[status] || 0})
          </button>
        ))}
      </div>
      
      {/* Orders Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShoppingCart className="w-5 h-5" />
            {statusFilter ? `${statusFilter} Orders` : 'All Orders'}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {orders && orders.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>Order ID</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Items</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Total</TableHead>
                <TableHead>Created</TableHead>
              </TableHeader>
              <TableBody>
                {orders.map((order) => (
                  <TableRow 
                    key={order.id}
                    onClick={() => setSelectedOrder(order.id)}
                    className="cursor-pointer"
                  >
                    <TableCell className="font-mono font-medium">#{order.id}</TableCell>
                    <TableCell>{order.customer_email}</TableCell>
                    <TableCell>{order.item_count} item(s)</TableCell>
                    <TableCell>
                      <StatusBadge status={order.status} />
                    </TableCell>
                    <TableCell className="font-mono">${order.total_amount}</TableCell>
                    <TableCell className="text-slate-400">
                      {new Date(order.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={ShoppingCart}
              title="No orders found"
              description={statusFilter ? `No orders with status "${statusFilter}"` : "No orders have been placed yet"}
            />
          )}
        </CardContent>
      </Card>
      
      <OrderDetailModal 
        open={!!selectedOrder}
        onClose={() => setSelectedOrder(null)}
        orderId={selectedOrder}
      />
    </div>
  );
}

