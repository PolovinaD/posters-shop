import { useState, useEffect, useMemo } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Package,
  CreditCard,
  Factory,
  Truck,
  CheckCircle,
  Clock,
  Search,
  ArrowRight,
  XCircle,
  Coins,
  ShieldCheck
} from 'lucide-react';
import { ordersApi, productionApi, paymentsApi } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { payInvoice, formatEth, payoutSplit, shortAddress, addressFromKey } from '../../lib/escrow';

const CANCELLABLE_STATUSES = ['created', 'reserved', 'paid'];

// escrow_status on the order row -> customer-facing label. `cancelled` reads
// as "Refunded" because cancel_order refunds the contract before it cancels.
const ESCROW_STATUS_LABELS = {
  awaiting_payment: 'Awaiting payment',
  funded: 'Funded',
  in_delivery: 'In delivery',
  released: 'Released',
  cancelled: 'Refunded',
  failed: 'Failed',
};

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
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [cancelError, setCancelError] = useState(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated && orderId) {
      navigate('/shop/login', { replace: true });
    }
  }, [authLoading, isAuthenticated, orderId, navigate]);

  const { data: order, isLoading, error } = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => ordersApi.getOrder(orderId),
    enabled: !!orderId && !authLoading && isAuthenticated,
    refetchInterval: 5000, // Poll for updates
  });

  const { mutate: cancelOrder, isPending: cancelling } = useMutation({
    mutationFn: () => ordersApi.cancelOrder(orderId),
    onSuccess: () => {
      setCancelError(null);
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      queryClient.invalidateQueries({ queryKey: ['myOrders'] });
    },
    onError: (err) => {
      setCancelError(err.message || 'Cannot cancel order');
    },
  });

  const { data: job } = useQuery({
    queryKey: ['job', orderId],
    queryFn: () => productionApi.getJobByOrder(orderId).catch(() => null),
    enabled: !!orderId && !authLoading && isAuthenticated && ['paid', 'producing', 'shipped', 'delivered'].includes(order?.status),
    refetchInterval: 5000,
  });

  // Ether escrow (ESC-05): stored row state + live chain state, polled like the
  // order itself so a payment or a courier binding shows up without a reload.
  const isEscrow = order?.payment_method === 'escrow';
  const { data: escrow } = useQuery({
    queryKey: ['escrow', orderId],
    queryFn: () => ordersApi.getEscrow(orderId),
    enabled: !!orderId && !authLoading && isAuthenticated && isEscrow,
    refetchInterval: 5000,
  });
  const { data: escrowConfig } = useQuery({
    queryKey: ['escrowConfig'],
    queryFn: paymentsApi.getEscrowConfig,
    enabled: isEscrow,
    staleTime: 30000,
    retry: false,
  });
  const [payKey, setPayKey] = useState('');
  const [payBusy, setPayBusy] = useState(false);
  const [escrowMsg, setEscrowMsg] = useState(null); // { kind: 'error' | 'ok', text }
  const payAddress = useMemo(() => {
    if (!payKey) return null;
    try {
      return addressFromKey(payKey);
    } catch {
      return null;
    }
  }, [payKey]);

  // Locked decision 1: the customer's authenticated click; the backend signs
  // confirmDelivery() with the owner key. A 409 carries the bare revert reason
  // ("Delivery not complete." when no courier is bound yet) and is shown as is.
  const confirmReceipt = useMutation({
    mutationFn: () => ordersApi.confirmEscrowDelivery(orderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['escrow', orderId] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      setEscrowMsg({ kind: 'ok', text: 'Payment released: 80 % to the shop, 20 % to the courier.' });
    },
    onError: (err) => {
      setEscrowMsg({ kind: 'error', text: err.message || 'Could not release the payment' });
    },
  });

  // "Pay now": the same deploy -> sign -> verify path as checkout, for an order
  // whose browser died (or whose key was wrong) before the payment landed.
  const payNow = async () => {
    setPayBusy(true);
    setEscrowMsg(null);
    try {
      const e = await ordersApi.createEscrow(orderId);
      await payInvoice({ rpcUrl: e.config.rpc_url, privateKey: payKey, invoice: e.invoice });
      const v = await ordersApi.verifyEscrow(orderId);
      if (v.status === 'paid' || v.status === 'already_paid') {
        setEscrowMsg({ kind: 'ok', text: 'Payment confirmed on chain. Your order is now paid.' });
      } else {
        setEscrowMsg({
          kind: 'error',
          text: `Payment not yet visible on chain (${v.chain_state}). It is re-checked automatically every few seconds.`,
        });
      }
      queryClient.invalidateQueries({ queryKey: ['escrow', orderId] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      setPayKey('');
    } catch (err) {
      setEscrowMsg({ kind: 'error', text: err.message || 'Payment failed' });
    } finally {
      setPayBusy(false);
    }
  };

  if (authLoading) return null;

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
  
  // Escrow panel inputs: the live read wins; the order row fills in before it
  // resolves (escrow_status is set at creation, the contract fields at deploy).
  const escrowState = escrow?.escrow_status ?? order.escrow_status;
  const contractAddress = escrow?.contract_address ?? order.escrow_contract_address;
  const amountWei = escrow?.amount_wei ?? order.escrow_amount_wei;
  const customerWallet = escrow?.customer_wallet ?? order.customer_wallet;
  const courierWallet = escrow?.courier_wallet ?? order.courier_wallet;
  const chainState = escrow?.chain?.state ?? (escrow?.chain_error ? 'unavailable' : '…');
  const canPay = order.status === 'reserved' && escrowState === 'awaiting_payment';
  const canConfirm = order.status === 'delivered' && escrow?.escrow_status === 'in_delivery';
  const split = escrowState === 'released' && amountWei
    ? payoutSplit(amountWei, escrowConfig?.courier_share_bps ?? 2000)
    : null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center gap-2 px-4 py-2 bg-stone-100 rounded-full text-stone-600 mb-4">
          <Package className="w-4 h-4" />
          Order #{order.id}
        </div>
        <h1 className="text-3xl font-bold text-stone-900 mb-2">
          {isEscrow && order.status === 'delivered' && escrow?.escrow_status === 'in_delivery'
             ? 'Delivered — confirm receipt to release the payment' :
           order.status === 'delivered' ? 'Order Delivered!' :
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

          {/* Ether escrow */}
          {isEscrow && (
            <div className="mt-6 bg-amber-50 rounded-2xl p-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <Coins className="w-5 h-5 text-amber-500" />
                  <span className="font-semibold text-amber-900">Ether escrow</span>
                </div>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                  {ESCROW_STATUS_LABELS[escrowState] ?? escrowState ?? '—'}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-amber-700">Contract</p>
                  <p className="font-medium font-mono text-amber-900" title={contractAddress || ''}>
                    {contractAddress ? shortAddress(contractAddress) : '—'}
                  </p>
                </div>
                <div>
                  <p className="text-amber-700">Amount</p>
                  <p className="font-medium text-amber-900">{amountWei ? `${formatEth(amountWei)} ETH` : '—'}</p>
                </div>
                <div>
                  <p className="text-amber-700">Your wallet</p>
                  <p className="font-medium font-mono text-amber-900" title={customerWallet || ''}>
                    {shortAddress(customerWallet) || '—'}
                  </p>
                </div>
                <div>
                  <p className="text-amber-700">Courier</p>
                  <p className="font-medium font-mono text-amber-900" title={courierWallet || ''}>
                    {shortAddress(courierWallet) || '—'}
                  </p>
                </div>
                <div>
                  <p className="text-amber-700">On chain</p>
                  <p className="font-medium text-amber-900">{chainState}</p>
                </div>
              </div>

              {canPay && (
                <div className="mt-5 bg-white rounded-xl p-4 border border-amber-200">
                  <p className="font-medium text-stone-900 mb-2">Pay now</p>
                  <p className="text-xs text-stone-500 mb-3">
                    Paste the private key of your wallet{customerWallet ? ` (${shortAddress(customerWallet)})` : ''}.
                    It is signed in your browser with ethers.js and never sent to the server.
                  </p>
                  <input
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={payKey}
                    onChange={(e) => setPayKey(e.target.value)}
                    placeholder="Private key 0x…"
                    className="w-full px-4 py-3 rounded-xl border border-stone-200 bg-white text-stone-900 font-mono placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                  />
                  {payKey && !payAddress && (
                    <p className="text-xs text-red-500 mt-1">Enter a valid 64-character hex key</p>
                  )}
                  {payAddress && (
                    <p className="text-xs text-stone-600 mt-1">
                      Paying from <span className="font-mono">{payAddress}</span>
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={payNow}
                    disabled={payBusy || !payAddress}
                    className="mt-3 w-full py-3 bg-gradient-to-r from-orange-500 to-amber-500 text-white font-semibold rounded-xl hover:from-orange-600 hover:to-amber-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {payBusy ? 'Sending payment…' : amountWei ? `Pay ${formatEth(amountWei)} ETH` : 'Pay now'}
                  </button>
                </div>
              )}

              {canConfirm && (
                <button
                  type="button"
                  onClick={() => confirmReceipt.mutate()}
                  disabled={confirmReceipt.isPending}
                  className="mt-5 w-full py-3 bg-green-600 text-white font-semibold rounded-xl hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  <ShieldCheck className="w-5 h-5" />
                  {confirmReceipt.isPending ? 'Releasing…' : 'Confirm receipt and release payment'}
                </button>
              )}

              {split && (
                <div className="mt-5 bg-white rounded-xl p-4 border border-amber-200 text-sm">
                  <p className="font-medium text-stone-900 mb-1">Paid out</p>
                  <p className="text-stone-600">
                    Shop {formatEth(split.ownerWei)} ETH · Courier {formatEth(split.courierWei)} ETH
                  </p>
                </div>
              )}

              {escrowMsg && (
                <p className={`mt-4 text-sm ${escrowMsg.kind === 'ok' ? 'text-green-700' : 'text-red-600'}`}>
                  {escrowMsg.text}
                </p>
              )}
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
              {order.shipping_address ? (
                <div className="text-sm text-stone-900">
                  <p className="font-medium">{order.shipping_address.recipient_name}</p>
                  <p>{order.shipping_address.street}</p>
                  <p>{order.shipping_address.postal_code} {order.shipping_address.city}</p>
                  <p>{order.shipping_address.country}</p>
                  <p className="text-stone-500 mt-1">{order.shipping_address.phone}</p>
                  <p className="text-stone-500">{order.customer_email}</p>
                </div>
              ) : (
                <p className="font-medium text-stone-900">{order.customer_email}</p>
              )}
            </div>
          </div>
          
          {CANCELLABLE_STATUSES.includes(order.status) && (
            <div className="mt-4 text-center">
              <button
                onClick={() => cancelOrder()}
                disabled={cancelling}
                className="text-sm text-red-600 hover:text-red-700 font-medium disabled:opacity-50 transition-colors"
              >
                {cancelling ? 'Cancelling...' : 'Cancel Order'}
              </button>
              {cancelError && (
                <p className="text-xs text-red-500 mt-1">{cancelError}</p>
              )}
            </div>
          )}

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

