import { clsx } from 'clsx';
import { Loader2, AlertCircle, CheckCircle2, XCircle } from 'lucide-react';

// Card component
export function Card({ children, className = '' }) {
  return (
    <div className={clsx(
      'bg-[#1e293b] border border-[#334155] rounded-xl',
      className
    )}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = '' }) {
  return (
    <div className={clsx('px-6 py-4 border-b border-[#334155]', className)}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }) {
  return (
    <h3 className={clsx('text-lg font-semibold', className)}>
      {children}
    </h3>
  );
}

export function CardContent({ children, className = '' }) {
  return (
    <div className={clsx('p-6', className)}>
      {children}
    </div>
  );
}

// Button component
export function Button({ 
  children, 
  variant = 'primary', 
  size = 'md',
  loading = false,
  disabled = false,
  className = '',
  ...props 
}) {
  const variants = {
    primary: { bg: 'bg-blue-500 hover:bg-blue-600', color: '#ffffff' },
    secondary: { bg: 'bg-slate-700 hover:bg-slate-600', color: '#ffffff' },
    success: { bg: 'bg-green-500 hover:bg-green-600', color: '#ffffff' },
    danger: { bg: 'bg-red-500 hover:bg-red-600', color: '#ffffff' },
    warning: { bg: 'bg-amber-500 hover:bg-amber-600', color: '#ffffff' },
    ghost: { bg: 'hover:bg-slate-700', color: '#cbd5e1' },
  };
  
  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2',
    lg: 'px-6 py-3 text-lg',
  };
  
  const variantConfig = variants[variant];
  
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-2 font-medium rounded-lg',
        'transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed',
        variantConfig.bg,
        sizes[size],
        className
      )}
      style={{ color: variantConfig.color }}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="w-4 h-4 animate-spin" />}
      {children}
    </button>
  );
}

// Status Badge
export function StatusBadge({ status, className = '' }) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
      `status-${status}`,
      className
    )}>
      {status}
    </span>
  );
}

// Stat Card for dashboard
export function StatCard({ title, value, subtitle, icon: Icon, trend, color = 'blue' }) {
  const colors = {
    blue: 'bg-blue-500/20 text-blue-400',
    green: 'bg-green-500/20 text-green-400',
    amber: 'bg-amber-500/20 text-amber-400',
    purple: 'bg-purple-500/20 text-purple-400',
    cyan: 'bg-cyan-500/20 text-cyan-400',
  };
  
  return (
    <Card>
      <CardContent className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-400">{title}</p>
          <p className="text-3xl font-bold mt-1">{value}</p>
          {subtitle && (
            <p className="text-sm text-slate-500 mt-1">{subtitle}</p>
          )}
          {trend !== undefined && (
            <p className={clsx(
              'text-sm mt-2',
              trend >= 0 ? 'text-green-400' : 'text-red-400'
            )}>
              {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}% from last hour
            </p>
          )}
        </div>
        {Icon && (
          <div className={clsx('p-3 rounded-lg', colors[color])}>
            <Icon className="w-6 h-6" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Loading spinner
export function Loading({ className = '' }) {
  return (
    <div className={clsx('flex items-center justify-center p-8', className)}>
      <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
    </div>
  );
}

// Error message
export function ErrorMessage({ message, retry }) {
  return (
    <div className="flex flex-col items-center justify-center p-8 text-center">
      <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
      <p className="text-slate-300 mb-4">{message}</p>
      {retry && (
        <Button onClick={retry} variant="secondary">
          Try Again
        </Button>
      )}
    </div>
  );
}

// Empty state
export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center">
      {Icon && <Icon className="w-12 h-12 text-slate-500 mb-4" />}
      <h3 className="text-lg font-medium text-slate-300 mb-2">{title}</h3>
      {description && <p className="text-slate-500 mb-4">{description}</p>}
      {action}
    </div>
  );
}

// Table components
export function Table({ children, className = '' }) {
  return (
    <div className="overflow-x-auto">
      <table className={clsx('w-full', className)}>
        {children}
      </table>
    </div>
  );
}

export function TableHeader({ children }) {
  return (
    <thead className="bg-slate-800/50">
      <tr>{children}</tr>
    </thead>
  );
}

export function TableHead({ children, className = '' }) {
  return (
    <th className={clsx(
      'px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider',
      className
    )}>
      {children}
    </th>
  );
}

export function TableBody({ children }) {
  return <tbody className="divide-y divide-slate-700">{children}</tbody>;
}

export function TableRow({ children, className = '', onClick }) {
  return (
    <tr 
      className={clsx(
        'hover:bg-slate-800/50 transition-colors',
        onClick && 'cursor-pointer',
        className
      )}
      onClick={onClick}
    >
      {children}
    </tr>
  );
}

export function TableCell({ children, className = '' }) {
  return (
    <td className={clsx('px-4 py-3 text-sm', className)}>
      {children}
    </td>
  );
}

// Health indicator
export function HealthIndicator({ status }) {
  if (status === 'healthy') {
    return <CheckCircle2 className="w-5 h-5 text-green-400" />;
  }
  return <XCircle className="w-5 h-5 text-red-400" />;
}

// Modal
export function Modal({ open, onClose, title, children }) {
  if (!open) return null;
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-[#1e293b] border border-[#334155] rounded-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#334155]">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <XCircle className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6">
          {children}
        </div>
      </div>
    </div>
  );
}

// Input
export function Input({ label, error, className = '', ...props }) {
  return (
    <div className={className}>
      {label && (
        <label className="block text-sm font-medium text-slate-300 mb-1">
          {label}
        </label>
      )}
      <input
        className={clsx(
          'w-full px-4 py-2 bg-slate-800 border rounded-lg',
          'focus:outline-none focus:ring-2 focus:ring-blue-500',
          'placeholder:text-slate-500',
          error ? 'border-red-500' : 'border-slate-600'
        )}
        style={{ color: '#f8fafc' }}
        {...props}
      />
      {error && <p className="mt-1 text-sm text-red-400">{error}</p>}
    </div>
  );
}

// Select
export function Select({ label, options, className = '', ...props }) {
  return (
    <div className={className}>
      {label && (
        <label className="block text-sm font-medium text-slate-300 mb-1">
          {label}
        </label>
      )}
      <select
        className="w-full px-4 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        {...props}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

