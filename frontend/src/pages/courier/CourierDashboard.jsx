import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Truck, LogOut } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authFetchJSON } from '../../api';

const NEXT_STATUS = {
  dispatched: 'in_transit',
  in_transit: 'delivered',
};

export default function CourierDashboard() {
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const queryClient = useQueryClient();
  const [pendingIds, setPendingIds] = useState(new Set());

  // Route guard: must be authenticated courier — wait for auth hydration first
  useEffect(() => {
    if (!authLoading && (!isAuthenticated || user?.role !== 'courier')) {
      navigate('/courier/login', { replace: true });
    }
  }, [authLoading, isAuthenticated, user, navigate]);

  const { data: allShipments = [], isLoading, error } = useQuery({
    queryKey: ['courier-shipments'],
    queryFn: () => authFetchJSON('/api/logistics/shipments'),
    enabled: isAuthenticated && user?.role === 'courier',
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
      await authFetchJSON(`/api/logistics/shipments/${shipment.id}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: nextStatus }),
      });
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
