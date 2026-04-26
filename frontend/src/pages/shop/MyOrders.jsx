import { Link, Navigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Package, Clock, CheckCircle, Truck, Factory, XCircle, ChevronRight } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { ordersApi } from '../../api';

const STATUS_CONFIG = {
  created: { label: 'Order Placed', icon: Clock, color: 'text-stone-600 bg-stone-50' },
  reserved: { label: 'Awaiting Payment', icon: Clock, color: 'text-amber-600 bg-amber-50' },
  paid: { label: 'Processing', icon: CheckCircle, color: 'text-blue-600 bg-blue-50' },
  producing: { label: 'In Production', icon: Factory, color: 'text-purple-600 bg-purple-50' },
  shipped: { label: 'Shipped', icon: Truck, color: 'text-cyan-600 bg-cyan-50' },
  delivered: { label: 'Delivered', icon: CheckCircle, color: 'text-green-600 bg-green-50' },
  cancelled: { label: 'Cancelled', icon: XCircle, color: 'text-red-600 bg-red-50' },
  failed: { label: 'Failed', icon: XCircle, color: 'text-red-600 bg-red-50' },
};

function OrderCard({ order }) {
  const config = STATUS_CONFIG[order.status] || STATUS_CONFIG.reserved;
  const Icon = config.icon;

  return (
    <Link
      to={`/shop/orders/${order.id}`}
      className="block bg-white rounded-2xl border border-stone-200 p-6 hover:shadow-md hover:border-orange-200 transition-all group"
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-sm text-stone-500">Order #{order.id}</p>
          <p className="text-lg font-semibold text-stone-900">${order.total_amount}</p>
        </div>
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium ${config.color}`}>
          <Icon className="w-4 h-4" />
          {config.label}
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-stone-500">
        <span>
          {order.item_count} {order.item_count === 1 ? 'item' : 'items'}
        </span>
        <span>
          {new Date(order.created_at).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
          })}
        </span>
      </div>

      <div className="mt-4 pt-4 border-t border-stone-100 flex items-center justify-between text-orange-600 group-hover:text-orange-700">
        <span className="text-sm font-medium">View Details</span>
        <ChevronRight className="w-4 h-4 transform group-hover:translate-x-1 transition-transform" />
      </div>
    </Link>
  );
}

export default function MyOrders() {
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();

  const { data: orders, isLoading, error } = useQuery({
    queryKey: ['myOrders', user?.email],
    queryFn: () => ordersApi.getOrders({ customer_email: user.email }),
    enabled: !!user?.email,
    refetchInterval: 10000,
  });

  if (authLoading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <div className="w-12 h-12 mx-auto mb-4 rounded-full border-4 border-orange-500 border-t-transparent animate-spin" />
        <p className="text-stone-500">Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/shop/login" state={{ from: '/shop/my-orders' }} replace />;
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-stone-900 mb-2">My Orders</h1>
        <p className="text-stone-500">
          Track and manage your orders, {user.name?.split(' ')[0] || 'there'}!
        </p>
      </div>

      {isLoading ? (
        <div className="text-center py-12">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full border-4 border-orange-500 border-t-transparent animate-spin" />
          <p className="text-stone-500">Loading your orders...</p>
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-100 flex items-center justify-center">
            <XCircle className="w-8 h-8 text-red-500" />
          </div>
          <p className="text-stone-900 font-medium mb-2">Failed to load orders</p>
          <p className="text-stone-500">{error.message}</p>
        </div>
      ) : orders && orders.length > 0 ? (
        <div className="grid gap-4">
          {orders.map((order) => (
            <OrderCard key={order.id} order={order} />
          ))}
        </div>
      ) : (
        <div className="text-center py-16">
          <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-stone-100 flex items-center justify-center">
            <Package className="w-10 h-10 text-stone-400" />
          </div>
          <h2 className="text-xl font-semibold text-stone-900 mb-2">No orders yet</h2>
          <p className="text-stone-500 mb-8">
            When you place your first order, it will appear here.
          </p>
          <Link
            to="/shop"
            className="inline-flex items-center gap-2 px-6 py-3 bg-orange-500 text-white font-semibold rounded-xl hover:bg-orange-600 transition-colors"
          >
            Start Shopping
          </Link>
        </div>
      )}
    </div>
  );
}
