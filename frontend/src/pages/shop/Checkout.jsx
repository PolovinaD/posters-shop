import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, CreditCard, Lock, Loader2, CheckCircle, Coins, Wallet as WalletIcon } from 'lucide-react';
import { useCart } from '../../context/CartContext';
import { useAuth } from '../../context/AuthContext';
import { ordersApi, paymentsApi } from '../../api';
import { addressFromKey, payInvoice, usdToWei, formatEth, shortAddress } from '../../lib/escrow';

const COUNTRIES = ['Serbia', 'Bosnia and Herzegovina', 'Croatia', 'Montenegro', 'North Macedonia', 'Slovenia', 'Hungary', 'Austria', 'Germany'];
const POSTAL_RE = /^[A-Za-z0-9][A-Za-z0-9 -]{1,11}$/;
const PHONE_RE = /^\+?[0-9][0-9 \-()]{4,19}$/;
const EMPTY_ADDRESS = { recipient_name: '', street: '', city: '', postal_code: '', country: COUNTRIES[0], phone: '' };

export default function Checkout() {
  const { items, total, clearCart } = useCart();
  const { user, isAuthenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState(EMPTY_ADDRESS);
  const [isLoading, setIsLoading] = useState(false);
  const [step, setStep] = useState('details'); // details, processing, complete
  const [orderId, setOrderId] = useState(null);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  // Ether escrow (ESC-05). The key is held in component state only, turned into
  // an address for display and into ONE signed transaction on submit, then
  // cleared. It is never part of any request body.
  const [paymentMethod, setPaymentMethod] = useState('stripe'); // stripe | escrow
  const [privateKey, setPrivateKey] = useState('');
  const [keyError, setKeyError] = useState(null);
  // Set once the escrow order exists and cleared only when verify succeeds, so a
  // failure after order creation can point the customer at "Pay now".
  const [pendingEscrow, setPendingEscrow] = useState(null);

  useEffect(() => {
    if (isAuthenticated && user?.email) {
      setEmail(user.email);
    }
  }, [isAuthenticated, user]);

  // Public read: with Ganache down (or escrow unconfigured) this says
  // enabled: false and the Ether option is simply not rendered.
  const { data: escrowConfig } = useQuery({
    queryKey: ['escrowConfig'],
    queryFn: paymentsApi.getEscrowConfig,
    staleTime: 30000,
    retry: false,
  });
  const escrowEnabled = !!escrowConfig?.enabled;
  const { data: demoAccounts = [] } = useQuery({
    queryKey: ['escrowDemoAccounts'],
    queryFn: () => paymentsApi.getEscrowDemoAccounts().catch(() => []),
    enabled: escrowEnabled && paymentMethod === 'escrow',
  });

  // If escrow becomes disabled while selected, fall back to Card.
  useEffect(() => {
    if (escrowConfig && !escrowConfig.enabled && paymentMethod === 'escrow') {
      setPaymentMethod('stripe');
    }
  }, [escrowConfig, paymentMethod]);

  const derivedAddress = useMemo(() => {
    if (!privateKey) return null;
    try {
      return addressFromKey(privateKey);
    } catch {
      return null;
    }
  }, [privateKey]);
  const ethAmount = escrowConfig ? formatEth(usdToWei(total, escrowConfig.wei_per_usd)) : null;
  const selectedDemoIndex = demoAccounts.find((a) => a.private_key === privateKey)?.index ?? '';

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

  const fieldClass = (name) => `w-full px-4 py-3 rounded-xl border ${
    fieldErrors[name] ? 'border-red-300' : 'border-stone-200'
  } bg-white text-stone-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent`;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setKeyError(null);

    const errors = validateAddress(address);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;   // stay on 'details', do not flip to 'processing'

    if (paymentMethod === 'escrow' && !derivedAddress) {
      setKeyError('Enter a valid private key or pick a demo account');
      return;
    }

    setIsLoading(true);
    setStep('processing');

    try {
      // 1. Create order
      const orderPayload = {
        customer_email: email,
        shipping_address: {
          recipient_name: address.recipient_name.trim(),
          street: address.street.trim(),
          city: address.city.trim(),
          postal_code: address.postal_code.trim(),
          country: address.country,
          phone: address.phone.trim(),
        },
        items: items.map(item => ({
          sku: item.sku,
          name: item.name,
          quantity: item.quantity,
          unit_price: item.price,
        })),
        payment_method: paymentMethod,
        ...(paymentMethod === 'escrow' ? { customer_wallet: derivedAddress } : {}),
      };

      if (paymentMethod === 'escrow') {
        // 2a. Deploy the per-order contract (idempotent), sign and send the
        //     single pay() invoice in the browser, then let orders read the chain.
        const order = await ordersApi.createOrder(orderPayload);
        setOrderId(order.id);
        setPendingEscrow({ orderId: order.id });
        const escrow = await ordersApi.createEscrow(order.id);
        await payInvoice({ rpcUrl: escrow.config.rpc_url, privateKey, invoice: escrow.invoice });
        const verified = await ordersApi.verifyEscrow(order.id);
        if (verified.status !== 'paid' && verified.status !== 'already_paid') {
          throw new Error(`Payment not yet visible on chain (${verified.chain_state}). Open the order and press "Pay now" to retry.`);
        }
        setPrivateKey('');
        clearCart();
        setPendingEscrow(null);
        setStep('complete');
        return;
      }

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
          {paymentMethod === 'escrow'
            ? 'Deploying the escrow contract and sending your payment. Please confirm nothing else — this takes a few seconds.'
            : 'Creating order and processing payment. Please wait.'}
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

            {/* Shipping Address */}
            <div className="space-y-4">
              <h2 className="text-lg font-semibold text-stone-900">Shipping Address</h2>

              <div>
                <label className="block text-sm font-medium text-stone-700 mb-2">
                  Recipient Name
                </label>
                <input
                  type="text"
                  value={address.recipient_name}
                  onChange={(e) => setAddress({ ...address, recipient_name: e.target.value })}
                  placeholder="Who should receive the parcel?"
                  className={fieldClass('recipient_name')}
                />
                {fieldErrors.recipient_name && (
                  <p className="text-xs text-red-500 mt-1">{fieldErrors.recipient_name}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-stone-700 mb-2">
                  Street and Number
                </label>
                <input
                  type="text"
                  value={address.street}
                  onChange={(e) => setAddress({ ...address, street: e.target.value })}
                  placeholder="Knez Mihailova 42"
                  className={fieldClass('street')}
                />
                {fieldErrors.street && (
                  <p className="text-xs text-red-500 mt-1">{fieldErrors.street}</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-2">
                    City
                  </label>
                  <input
                    type="text"
                    value={address.city}
                    onChange={(e) => setAddress({ ...address, city: e.target.value })}
                    placeholder="Beograd"
                    className={fieldClass('city')}
                  />
                  {fieldErrors.city && (
                    <p className="text-xs text-red-500 mt-1">{fieldErrors.city}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-2">
                    Postal Code
                  </label>
                  <input
                    type="text"
                    value={address.postal_code}
                    onChange={(e) => setAddress({ ...address, postal_code: e.target.value })}
                    placeholder="11000"
                    className={fieldClass('postal_code')}
                  />
                  {fieldErrors.postal_code && (
                    <p className="text-xs text-red-500 mt-1">{fieldErrors.postal_code}</p>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-2">
                    Country
                  </label>
                  <select
                    value={address.country}
                    onChange={(e) => setAddress({ ...address, country: e.target.value })}
                    className={fieldClass('country')}
                  >
                    {COUNTRIES.map((country) => (
                      <option key={country} value={country}>{country}</option>
                    ))}
                  </select>
                  {fieldErrors.country && (
                    <p className="text-xs text-red-500 mt-1">{fieldErrors.country}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-2">
                    Phone
                  </label>
                  <input
                    type="tel"
                    value={address.phone}
                    onChange={(e) => setAddress({ ...address, phone: e.target.value })}
                    placeholder="+381 60 123 4567"
                    className={fieldClass('phone')}
                  />
                  {fieldErrors.phone && (
                    <p className="text-xs text-red-500 mt-1">{fieldErrors.phone}</p>
                  )}
                </div>
              </div>
            </div>

            {/* Payment */}
            <div className="bg-stone-50 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="w-5 h-5 text-stone-400" />
                <span className="font-medium text-stone-900">Payment</span>
              </div>

              <div className="space-y-3">
                <label
                  className={`flex items-start gap-3 bg-white rounded-xl p-4 border cursor-pointer transition-colors ${
                    paymentMethod === 'stripe' ? 'border-orange-400 ring-2 ring-orange-100' : 'border-stone-200'
                  }`}
                >
                  <input
                    type="radio"
                    name="payment_method"
                    value="stripe"
                    checked={paymentMethod === 'stripe'}
                    onChange={() => setPaymentMethod('stripe')}
                    className="mt-1 accent-orange-500"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <CreditCard className="w-4 h-4 text-stone-500" />
                      <span className="font-medium text-stone-900">Card (Stripe)</span>
                    </div>
                    <p className="text-sm text-stone-500 mt-1">
                      You will be redirected to Stripe's secure checkout
                    </p>
                    <p className="text-xs text-stone-400 mt-1">
                      Demo card: <span className="font-mono text-stone-500">4242 4242 4242 4242</span> — no real payment will be processed.
                    </p>
                  </div>
                </label>

                {escrowEnabled && (
                  <label
                    className={`flex items-start gap-3 bg-white rounded-xl p-4 border cursor-pointer transition-colors ${
                      paymentMethod === 'escrow' ? 'border-orange-400 ring-2 ring-orange-100' : 'border-stone-200'
                    }`}
                  >
                    <input
                      type="radio"
                      name="payment_method"
                      value="escrow"
                      checked={paymentMethod === 'escrow'}
                      onChange={() => setPaymentMethod('escrow')}
                      className="mt-1 accent-orange-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <Coins className="w-4 h-4 text-amber-500" />
                        <span className="font-medium text-stone-900">Ether (escrow)</span>
                      </div>
                      <p className="text-sm text-stone-500 mt-1">
                        Pay {ethAmount} ETH into a per-order escrow contract; released to the shop and the courier when you confirm delivery
                      </p>
                    </div>
                  </label>
                )}
              </div>

              {escrowEnabled && paymentMethod === 'escrow' && (
                <div className="mt-4 bg-white rounded-xl p-4 border border-stone-200 space-y-4">
                  {demoAccounts.length > 0 && (
                    <div>
                      <label className="block text-sm font-medium text-stone-700 mb-2">
                        Use demo account
                      </label>
                      <select
                        value={selectedDemoIndex}
                        onChange={(e) => {
                          const picked = demoAccounts.find((a) => String(a.index) === e.target.value);
                          setPrivateKey(picked ? picked.private_key : '');
                          setKeyError(null);
                        }}
                        className={fieldClass('demo_account')}
                      >
                        <option value="">— pick a Ganache account —</option>
                        {demoAccounts.map((a) => (
                          <option key={a.index} value={a.index}>
                            Account {a.index} — {shortAddress(a.address)}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium text-stone-700 mb-2">
                      Private key
                    </label>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={privateKey}
                      onChange={(e) => {
                        setPrivateKey(e.target.value);
                        setKeyError(null);
                      }}
                      placeholder="0x…"
                      className={`${fieldClass('private_key')} font-mono`}
                    />
                    <p className="text-xs text-stone-400 mt-1">
                      Signed in your browser with ethers.js — the key is never sent to the server
                    </p>
                    {privateKey && !derivedAddress && (
                      <p className="text-xs text-red-500 mt-1">Enter a valid 64-character hex key</p>
                    )}
                    {derivedAddress && (
                      <p className="flex items-center gap-2 text-sm text-stone-700 mt-2">
                        <WalletIcon className="w-4 h-4 text-stone-400" />
                        Paying from <span className="font-mono" title={derivedAddress}>{derivedAddress}</span>
                      </p>
                    )}
                    {keyError && (
                      <p className="text-xs text-red-500 mt-1">{keyError}</p>
                    )}
                  </div>
                </div>
              )}
            </div>

            {error && (
              <div className="bg-red-50 text-red-600 px-4 py-3 rounded-xl">
                {error}
              </div>
            )}
            {pendingEscrow && (
              <div className="bg-amber-50 text-amber-800 px-4 py-3 rounded-xl text-sm">
                Order #{pendingEscrow.orderId} was created.{' '}
                <Link
                  to={`/shop/orders/${pendingEscrow.orderId}`}
                  className="font-semibold underline hover:text-amber-900"
                >
                  Pay now
                </Link>{' '}
                to finish paying.
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading || !email || (paymentMethod === 'escrow' && !derivedAddress)}
              className="w-full py-4 bg-gradient-to-r from-orange-500 to-amber-500 text-white font-semibold rounded-xl hover:from-orange-600 hover:to-amber-600 transition-all shadow-lg shadow-orange-500/25 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <Lock className="w-4 h-4" />
              {paymentMethod === 'escrow'
                ? `Pay ${ethAmount} ETH • $${total.toFixed(2)}`
                : `Place Order • $${total.toFixed(2)}`}
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


// Mirrors the ShippingAddress Field(...) constraints in
// services/orders/schemas.py one for one. A client rule looser than the server
// produces a confusing 422; a stricter one silently blocks valid input.
function validateAddress(a) {
  // Trim first and test the trimmed value: the server sets
  // str_strip_whitespace=True, so it validates the stripped string. Running the
  // regex on the raw value would reject " 11000", which the server accepts.
  const v = {
    recipient_name: a.recipient_name.trim(),
    street: a.street.trim(),
    city: a.city.trim(),
    postal_code: a.postal_code.trim(),
    country: a.country.trim(),
    phone: a.phone.trim(),
  };

  const errors = {};

  // The length rules are not padding. POSTAL_RE alone accepts "A1"/"11" and
  // PHONE_RE alone accepts "12345" and a 21-char number — all rejected by the
  // server with a 422 whose `detail` is an ARRAY OF OBJECTS, which api.js:95
  // (`error.detail || ...`) surfaces to the customer as "[object Object]".
  // The bounds are compared in CODE POINTS, not UTF-16 units: pydantic's
  // min_length/max_length count code points (len('👍') === 1) while JS .length
  // counts UTF-16 units ('👍'.length === 2), so a bare .length let a single-emoji
  // name through the form and straight into that same 422. Spreading into an array
  // before measuring is the code-point-counting form, and it fixes the max bound in
  // the same motion.
  if ([...v.recipient_name].length < 2 || [...v.recipient_name].length > 120) {
    errors.recipient_name = "Enter the recipient's full name";
  }
  if ([...v.street].length < 3 || [...v.street].length > 200) {
    errors.street = 'Enter the street and number';
  }
  if ([...v.city].length < 2 || [...v.city].length > 100) {
    errors.city = 'Enter the city';
  }
  if ([...v.postal_code].length < 3 || [...v.postal_code].length > 12 || !POSTAL_RE.test(v.postal_code)) {
    errors.postal_code = 'Enter a valid postal code';
  }
  // Length bounds mirror the server's Field(min_length=2, max_length=56). The
  // <select> only ever yields a COUNTRIES entry, so this is unreachable through
  // the UI — but without it the client accepts a 1-char country the server 422s.
  if ([...v.country].length < 2 || [...v.country].length > 56) {
    errors.country = 'Select a country';
  }
  if ([...v.phone].length < 6 || [...v.phone].length > 20 || !PHONE_RE.test(v.phone)) {
    errors.phone = 'Enter a reachable phone number, digits only';
  }

  return errors;
}
