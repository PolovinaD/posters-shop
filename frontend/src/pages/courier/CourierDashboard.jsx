import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Truck, LogOut, MapPin, Wallet as WalletIcon, Save } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authFetchJSON, usersApi, logisticsApi } from '../../api';
import { formatAddressLines } from '../../lib/address';
import { shortAddress } from '../../lib/escrow';

const NEXT_STATUS = {
  dispatched: 'in_transit',
  in_transit: 'delivered',
};

const WALLET_RE = /^0x[0-9a-fA-F]{40}$/;

export default function CourierDashboard() {
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const queryClient = useQueryClient();
  const [pendingIds, setPendingIds] = useState(new Set());
  const [walletInput, setWalletInput] = useState('');
  const [walletNote, setWalletNote] = useState(null); // { kind: 'ok' | 'error', text }

  // Route guard: must be authenticated courier — wait for auth hydration first
  useEffect(() => {
    if (!authLoading && (!isAuthenticated || user?.role !== 'courier')) {
      navigate('/courier/login', { replace: true });
    }
  }, [authLoading, isAuthenticated, user, navigate]);

  const isCourier = isAuthenticated && user?.role === 'courier';

  const { data: allShipments = [], isLoading, error } = useQuery({
    queryKey: ['courier-shipments'],
    queryFn: () => authFetchJSON('/api/logistics/shipments'),
    enabled: isCourier,
  });

  // Fresh profile, not `user`: AuthContext caches the login-time /users/me
  // payload in localStorage, so a wallet saved after login is only visible
  // through a new read (ESC-04).
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: usersApi.getMe,
    enabled: isCourier,
  });

  useEffect(() => {
    setWalletInput(me?.wallet_address ?? '');
  }, [me]);

  const walletValid = WALLET_RE.test(walletInput.trim());
  const walletChanged = walletInput.trim() !== (me?.wallet_address ?? '');

  const saveWallet = useMutation({
    mutationFn: () => usersApi.setWallet(walletInput.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] });
      setWalletNote({ kind: 'ok', text: 'Wallet saved' });
    },
    onError: (err) => {
      setWalletNote({ kind: 'error', text: err.message || 'Could not save the wallet' });
    },
  });

  const activeShipments = allShipments.filter(
    (s) => s.status === 'dispatched' || s.status === 'in_transit'
  );

  const handleLogout = async () => {
    await logout();
    navigate('/courier/login', { replace: true });
  };

  const handleAdvanceStatus = async (shipment) => {
    const nextStatus = NEXT_STATUS[shipment.status];
    if (!nextStatus) return;

    setPendingIds((prev) => new Set([...prev, shipment.id]));
    try {
      // Pick-up (dispatched -> in_transit) carries the payout wallet so orders
      // can bind this courier on an escrow contract; the other transition
      // sends the bare status body as before.
      const courierWallet = nextStatus === 'in_transit' ? (me?.wallet_address || undefined) : undefined;
      await logisticsApi.updateShipmentStatus(shipment.id, nextStatus, courierWallet);
      queryClient.invalidateQueries({ queryKey: ['courier-shipments'] });
    } catch (err) {
      console.error('Failed to advance shipment status:', err);
    } finally {
      setPendingIds((prev) => {
        const next = new Set(prev);
        next.delete(shipment.id);
        return next;
      });
    }
  };

  if (authLoading || !isAuthenticated || user?.role !== 'courier') {
    return null;
  }

  return (
    <div className="min-h-screen bg-[#0f172a] text-white">
      {/* Header */}
      <header className="bg-[#1e293b] border-b border-[#334155] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Truck className="w-6 h-6 text-blue-400" />
          <h1 className="text-xl font-semibold">Courier Dashboard</h1>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 text-slate-400 hover:text-white text-sm transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
      </header>

      {/* Main content */}
      <main className="px-6 py-8 max-w-4xl mx-auto">
        {/* Payout wallet */}
        <div className="bg-[#1e293b] border border-[#334155] rounded-xl px-5 py-4 mb-8">
          <div className="flex items-center gap-2 mb-3">
            <WalletIcon className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-medium text-slate-300">Payout wallet</h2>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={walletInput}
              onChange={(e) => {
                setWalletInput(e.target.value);
                setWalletNote(null);
              }}
              placeholder="0x…"
              spellCheck={false}
              className="flex-1 bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              type="button"
              onClick={() => saveWallet.mutate()}
              disabled={!walletValid || !walletChanged || saveWallet.isPending}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              {saveWallet.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-2">
            Escrow orders pay 20 % of the order to this address when the customer confirms delivery. Set it before picking a parcel up.
          </p>
          {walletInput && !walletValid && (
            <p className="text-xs text-red-400 mt-1">Enter an address of the form 0x + 40 hex characters</p>
          )}
          {me?.wallet_address && (
            <p className="text-xs text-slate-400 mt-1">
              Current: <span className="font-mono" title={me.wallet_address}>{shortAddress(me.wallet_address)}</span>
            </p>
          )}
          {walletNote && (
            <p className={`text-xs mt-1 ${walletNote.kind === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
              {walletNote.text}
            </p>
          )}
        </div>

        <h2 className="text-lg font-medium text-slate-300 mb-6">Active Shipments</h2>

        {isLoading && (
          <div className="flex items-center justify-center py-16 text-slate-400">
            <Loader2 className="w-6 h-6 animate-spin mr-2" />
            Loading shipments...
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm">
            Failed to load shipments: {error.message}
          </div>
        )}

        {!isLoading && !error && activeShipments.length === 0 && (
          <div className="text-center py-16 text-slate-500">
            No active shipments
          </div>
        )}

        {!isLoading && !error && activeShipments.length > 0 && (
          <div className="space-y-3">
            {activeShipments.map((shipment) => {
              const isPending = pendingIds.has(shipment.id);
              const nextStatus = NEXT_STATUS[shipment.status];
              const addressLines = formatAddressLines(shipment.shipping_address);
              const pickupWithoutWallet = nextStatus === 'in_transit' && !me?.wallet_address;

              return (
                <div
                  key={shipment.id}
                  className="bg-[#1e293b] border border-[#334155] rounded-xl px-5 py-4 flex items-center justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-3">
                      <span className="font-semibold text-white">{shipment.tracking}</span>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          shipment.status === 'dispatched'
                            ? 'bg-yellow-500/20 text-yellow-400'
                            : 'bg-blue-500/20 text-blue-400'
                        }`}
                      >
                        {shipment.status}
                      </span>
                    </div>
                    <p className="text-sm text-slate-400">Order #{shipment.order_id}</p>

                    {addressLines.length > 0 ? (
                      <div className="flex items-start gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-slate-500 mt-1 shrink-0" />
                        <div>
                          {addressLines.map((line, i) => (
                            <p
                              key={i}
                              className={`text-sm ${i === 0 ? 'text-slate-300' : 'text-slate-400'}`}
                            >
                              {line}
                            </p>
                          ))}
                        </div>
                      </div>
                    ) : (
                      // Muted-but-present beats silence: a courier must be able to tell
                      // "no address stored" apart from "the page forgot to render it".
                      <p className="text-sm text-slate-500 italic">No delivery address on file</p>
                    )}

                    {pickupWithoutWallet && (
                      <p className="text-xs text-amber-400">
                        No payout wallet set — pick-up still works, but an escrow order will pay the default courier wallet.
                      </p>
                    )}
                  </div>

                  {nextStatus && (
                    <button
                      onClick={() => handleAdvanceStatus(shipment)}
                      disabled={isPending}
                      className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                    >
                      {isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                      Advance Status
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
