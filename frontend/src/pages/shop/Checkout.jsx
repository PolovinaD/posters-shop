import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, CreditCard, Lock, Loader2, CheckCircle } from 'lucide-react';
import { useCart } from '../../context/CartContext';
import { useAuth } from '../../context/AuthContext';
import { ordersApi } from '../../api';

export default function Checkout() {
  const navigate = useNavigate();
  const { items, total, clearCart } = useCart();
  const { user, isAuthenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [step, setStep] = useState('details'); // details, processing, complete
  const [orderId, setOrderId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isAuthenticated && user?.email) {
      setEmail(user.email);
    }
  }, [isAuthenticated, user]);
  
  if (items.length === 0 && step === 'details') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <h1 className="text-2xl font-bold text-stone-900 mb-4">Your cart is empty</h1>
        <Link 
          to="/shop" 
          className="text-orange-600 hover:text-orange-700 font-medium"
        >
          ← Continue shopping
        </Link>
      </div>
    );
  }
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    setStep('processing');
    
    try {
      // 1. Create order
      const orderPayload = {
        customer_email: email,
        items: items.map(item => ({
          sku: item.sku,
          name: item.name,
          quantity: item.quantity,
          unit_price: item.price,
        })),
      };
      
      const order = await ordersApi.createOrder(orderPayload);
      setOrderId(order.id);
      
      // 2. Create checkout session and redirect to Stripe
      const checkout = await ordersApi.createCheckout(order.id);
      clearCart();
      window.location.href = checkout.checkout_url;
      
    } catch (err) {
      setError(err.message || 'Something went wrong');
      setStep('details');
    } finally {
      setIsLoading(false);
    }
  };
  
  if (step === 'processing') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-orange-100 flex items-center justify-center">
          <Loader2 className="w-10 h-10 text-orange-500 animate-spin" />
        </div>
        <h1 className="text-2xl font-bold text-stone-900 mb-4">Processing your order...</h1>
        <p className="text-stone-600">
          Creating order and processing payment. Please wait.
        </p>
      </div>
    );
  }
  
  if (step === 'complete') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-green-100 flex items-center justify-center">
          <CheckCircle className="w-10 h-10 text-green-500" />
        </div>
        <h1 className="text-2xl font-bold text-stone-900 mb-4">Order Confirmed!</h1>
        <p className="text-stone-600 mb-2">
          Thank you for your order. Your order number is:
        </p>
        <p className="text-3xl font-mono font-bold text-orange-600 mb-8">
          #{orderId}
        </p>
        <p className="text-stone-500 mb-8">
          We've sent a confirmation to <span className="font-medium">{email}</span>
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            to={`/shop/orders/${orderId}`}
            className="px-6 py-3 bg-orange-500 text-white font-semibold rounded-xl hover:bg-orange-600 transition-colors"
          >
            Track Order
          </Link>
          <Link
            to="/shop"
            className="px-6 py-3 bg-stone-100 text-stone-900 font-semibold rounded-xl hover:bg-stone-200 transition-colors"
          >
            Continue Shopping
          </Link>
        </div>
      </div>
    );
  }
  
  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <Link 
        to="/shop" 
        className="inline-flex items-center gap-2 text-stone-500 hover:text-stone-700 mb-8"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Shop
      </Link>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* Checkout Form */}
        <div>
          <h1 className="text-3xl font-bold text-stone-900 mb-8">Checkout</h1>
          
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Email Address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                required
                readOnly={isAuthenticated}
                className={`w-full px-4 py-3 rounded-xl border border-stone-200 text-stone-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent ${
                  isAuthenticated ? 'bg-stone-50' : 'bg-white'
                }`}
              />
              <p className="text-sm text-stone-500 mt-1">
                {isAuthenticated 
                  ? 'Using your account email' 
                  : 'We\'ll send order confirmation and tracking info here'
                }
              </p>
            </div>
            
            {/* Payment Info (Demo) */}
            <div className="bg-stone-50 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="w-5 h-5 text-stone-400" />
                <span className="font-medium text-stone-900">Payment</span>
              </div>
              <div className="bg-white rounded-xl p-4 border border-stone-200">
                <p className="text-sm text-stone-500 mb-2">Demo Mode</p>
                <p className="font-mono text-stone-700">4242 4242 4242 4242</p>
                <p className="text-xs text-stone-400 mt-1">
                  This is a demo. No real payment will be processed.
                </p>
              </div>
            </div>
            
            {error && (
              <div className="bg-red-50 text-red-600 px-4 py-3 rounded-xl">
                {error}
              </div>
            )}
            
            <button
              type="submit"
              disabled={isLoading || !email}
              className="w-full py-4 bg-gradient-to-r from-orange-500 to-amber-500 text-white font-semibold rounded-xl hover:from-orange-600 hover:to-amber-600 transition-all shadow-lg shadow-orange-500/25 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <Lock className="w-4 h-4" />
              Place Order • ${total.toFixed(2)}
            </button>
            
            <p className="text-center text-sm text-stone-500">
              By placing your order, you agree to our Terms of Service.
            </p>
          </form>
        </div>
        
        {/* Order Summary */}
        <div>
          <div className="bg-stone-50 rounded-2xl p-6 lg:sticky lg:top-24">
            <h2 className="text-lg font-semibold text-stone-900 mb-6">Order Summary</h2>
            
            <ul className="divide-y divide-stone-200">
              {items.map((item) => (
                <li key={item.sku} className="py-4 flex gap-4">
                  <img
                    src={item.image}
                    alt={item.name}
                    className="w-16 h-20 object-cover rounded-lg"
                  />
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-stone-900">{item.name}</h3>
                    <p className="text-sm text-stone-500">Qty: {item.quantity}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-medium text-stone-900">
                      ${(item.price * item.quantity).toFixed(2)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
            
            <div className="border-t border-stone-200 mt-4 pt-4 space-y-2">
              <div className="flex justify-between text-stone-600">
                <span>Subtotal</span>
                <span>${total.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-stone-600">
                <span>Shipping</span>
                <span className="text-green-600">Free</span>
              </div>
              <div className="flex justify-between text-lg font-bold text-stone-900 pt-2 border-t border-stone-200">
                <span>Total</span>
                <span>${total.toFixed(2)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

