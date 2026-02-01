import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { 
  Package, 
  CreditCard, 
  Factory, 
  Truck, 
  CheckCircle, 
  Clock,
  Search,
  ArrowRight,
  XCircle
} from 'lucide-react';
import { ordersApi, productionApi, logisticsApi } from '../../api';

const STATUS_STEPS = [
  { status: 'reserved', label: 'Order Placed', icon: Clock, description: 'Waiting for payment' },
  { status: 'paid', label: 'Payment Confirmed', icon: CreditCard, description: 'Processing your order' },
  { status: 'producing', label: 'In Production', icon: Factory, description: 'Printing your posters' },
  { status: 'shipped', label: 'Shipped', icon: Truck, description: 'On the way to you' },
  { status: 'delivered', label: 'Delivered', icon: CheckCircle, description: 'Enjoy your prints!' },
];

function OrderTimeline({ currentStatus }) {
  const currentIndex = STATUS_STEPS.findIndex(s => s.status === currentStatus);
  const isCancelled = currentStatus === 'cancelled';
  const isFailed = currentStatus === 'failed';
  
  if (isCancelled || isFailed) {
    return (
      <div className="text-center py-8">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-100 flex items-center justify-center">
          <XCircle className="w-8 h-8 text-red-500" />
        </div>
        <p className="text-lg font-medium text-red-600">
          Order {currentStatus}
        </p>
      </div>
    );
  }
  
  return (
    <div className="relative">
      {/* Progress line */}
      <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-stone-200" />
      <div 
        className="absolute left-6 top-0 w-0.5 bg-gradient-to-b from-orange-500 to-amber-500 transition-all duration-500"
        style={{ height: `${Math.max(0, (currentIndex / (STATUS_STEPS.length - 1)) * 100)}%` }}
      />
      
      {/* Steps */}
      <div className="space-y-8">
        {STATUS_STEPS.map((step, index) => {
          const Icon = step.icon;
          const isPast = index < currentIndex;
          const isCurrent = index === currentIndex;
          const isFuture = index > currentIndex;
          
          return (
            <div key={step.status} className="relative flex items-start gap-4 pl-12">
              {/* Icon */}
              <div className={`
                absolute left-0 w-12 h-12 rounded-full flex items-center justify-center
                transition-all duration-300
                ${isCurrent 
                  ? 'bg-gradient-to-br from-orange-500 to-amber-500 text-white shadow-lg shadow-orange-500/30 scale-110' 
                  : isPast 
                    ? 'bg-green-100 text-green-600' 
                    : 'bg-stone-100 text-stone-400'
                }
              `}>
                <Icon className="w-5 h-5" />
              </div>
              
              {/* Content */}
              <div className="pt-2">
                <h3 className={`font-semibold ${isFuture ? 'text-stone-400' : 'text-stone-900'}`}>
                  {step.label}
                </h3>
                <p className={`text-sm ${isFuture ? 'text-stone-300' : 'text-stone-500'}`}>
                  {step.description}
                </p>
                {isCurrent && (
                  <span className="inline-flex items-center gap-1 mt-2 px-3 py-1 bg-orange-100 text-orange-600 text-sm font-medium rounded-full">
                    <span className="w-2 h-2 rounded-full bg-orange-500 animate-pulse" />
                    Current Status
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OrderLookup() {
  const [orderId, setOrderId] = useState('');
  
  return (
    <div className="max-w-md mx-auto">
      <div className="text-center mb-8">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-orange-100 to-amber-100 flex items-center justify-center">
          <Search className="w-8 h-8 text-orange-500" />
        </div>
        <h1 className="text-2xl font-bold text-stone-900 mb-2">Track Your Order</h1>
        <p className="text-stone-500">Enter your order number to see the status</p>
      </div>
      
      <form 
        onSubmit={(e) => {
          e.preventDefault();
          if (orderId) {
            window.location.href = `/shop/orders/${orderId}`;
          }
        }}
        className="flex gap-3"
      >
        <input
          type="text"
          value={orderId}
          onChange={(e) => setOrderId(e.target.value)}
          placeholder="Order number (e.g., 1)"
          className="flex-1 px-4 py-3 rounded-xl border border-stone-200 focus:outline-none focus:ring-2 focus:ring-orange-500"
        />
        <button
          type="submit"
          className="px-6 py-3 bg-orange-500 text-white font-semibold rounded-xl hover:bg-orange-600 transition-colors flex items-center gap-2"
        >
          Track
          <ArrowRight className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}

export default function OrderTracking() {
  const { orderId } = useParams();
  
  const { data: order, isLoading, error } = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => ordersApi.getOrder(orderId),
    enabled: !!orderId,
    refetchInterval: 5000, // Poll for updates
  });
  
  const { data: job } = useQuery({
    queryKey: ['job', orderId],
    queryFn: () => productionApi.getJobByOrder(orderId).catch(() => null),
    enabled: !!orderId && ['paid', 'producing', 'shipped', 'delivered'].includes(order?.status),
    refetchInterval: 5000,
  });
  
  // If no order ID, show lookup form
  if (!orderId) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20">
        <OrderLookup />
      </div>
    );
  }
  
  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <div className="w-12 h-12 mx-auto mb-4 rounded-full border-4 border-orange-500 border-t-transparent animate-spin" />
        <p className="text-stone-500">Loading order details...</p>
      </div>
    );
  }
  
  if (error || !order) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-100 flex items-center justify-center">
          <XCircle className="w-8 h-8 text-red-500" />
        </div>
        <h1 className="text-2xl font-bold text-stone-900 mb-2">Order Not Found</h1>
        <p className="text-stone-500 mb-8">
          We couldn't find an order with that number.
        </p>
        <Link
          to="/shop/orders"
          className="text-orange-600 hover:text-orange-700 font-medium"
        >
          ← Try another order number
        </Link>
      </div>
    );
  }
  
  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center gap-2 px-4 py-2 bg-stone-100 rounded-full text-stone-600 mb-4">
          <Package className="w-4 h-4" />
          Order #{order.id}
        </div>
        <h1 className="text-3xl font-bold text-stone-900 mb-2">
          {order.status === 'delivered' ? 'Order Delivered!' :
           order.status === 'shipped' ? 'Your order is on its way!' :
           order.status === 'producing' ? 'We\'re making your prints!' :
           order.status === 'paid' ? 'Order Confirmed!' :
           'Order Status'}
        </h1>
        <p className="text-stone-500">
          Placed on {new Date(order.created_at).toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
          })}
        </p>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Timeline */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-2xl p-8 shadow-sm border border-stone-100">
            <OrderTimeline currentStatus={order.status} />
          </div>
          
          {/* Production Info */}
          {job && (
            <div className="mt-6 bg-purple-50 rounded-2xl p-6">
              <div className="flex items-center gap-3 mb-3">
                <Factory className="w-5 h-5 text-purple-500" />
                <span className="font-semibold text-purple-900">Production Details</span>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-purple-600">Job Status</p>
                  <p className="font-medium text-purple-900 capitalize">{job.status}</p>
                </div>
                {job.processing_time_ms && (
                  <div>
                    <p className="text-purple-600">Print Time</p>
                    <p className="font-medium text-purple-900">{job.processing_time_ms}ms</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        
        {/* Order Summary */}
        <div>
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-stone-100">
            <h2 className="font-semibold text-stone-900 mb-4">Order Summary</h2>
            
            <div className="space-y-4 mb-6">
              {order.items?.map((item, i) => (
                <div key={i} className="flex justify-between text-sm">
                  <div>
                    <p className="font-medium text-stone-900">{item.name}</p>
                    <p className="text-stone-500">Qty: {item.quantity}</p>
                  </div>
                  <p className="font-medium text-stone-900">
                    ${(item.unit_price * item.quantity).toFixed(2)}
                  </p>
                </div>
              ))}
            </div>
            
            <div className="border-t border-stone-100 pt-4">
              <div className="flex justify-between font-bold text-stone-900">
                <span>Total</span>
                <span>${order.total_amount}</span>
              </div>
            </div>
            
            <div className="mt-6 pt-4 border-t border-stone-100">
              <p className="text-sm text-stone-500 mb-1">Shipping to</p>
              <p className="font-medium text-stone-900">{order.customer_email}</p>
            </div>
          </div>
          
          <div className="mt-4 text-center">
            <Link
              to="/shop"
              className="text-orange-600 hover:text-orange-700 font-medium text-sm"
            >
              ← Continue Shopping
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

