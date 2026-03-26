import { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Mail, Lock, User, Loader2, ArrowRight, Eye, EyeOff, Check, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

const PASSWORD_REQUIREMENTS = [
  { id: 'length', label: 'At least 8 characters', test: (pw) => pw.length >= 8 },
  { id: 'uppercase', label: 'One uppercase letter', test: (pw) => /[A-Z]/.test(pw) },
  { id: 'lowercase', label: 'One lowercase letter', test: (pw) => /[a-z]/.test(pw) },
  { id: 'number', label: 'One number', test: (pw) => /[0-9]/.test(pw) },
];

export default function Register() {
  const navigate = useNavigate();
  const location = useLocation();
  const { register } = useAuth();
  
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const from = location.state?.from || '/shop';

  const passwordChecks = PASSWORD_REQUIREMENTS.map(req => ({
    ...req,
    passed: req.test(password),
  }));

  const allRequirementsMet = passwordChecks.every(check => check.passed);
  const passwordsMatch = password === confirmPassword && confirmPassword.length > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (!allRequirementsMet) {
      setError('Password does not meet all requirements');
      return;
    }

    if (!passwordsMatch) {
      setError('Passwords do not match');
      return;
    }

    setIsLoading(true);

    try {
      await register({
        name,
        email,
        password,
        role: 'customer',
      });
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message || 'Registration failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-stone-900 mb-2">Create Account</h1>
          <p className="text-stone-500">Join PosterShop to track your orders</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-stone-200 p-8">
          {error && (
            <div className="mb-6 p-4 bg-red-50 text-red-600 rounded-xl text-sm">
              {error}
            </div>
          )}

          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Full Name
              </label>
              <div className="relative">
                <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-stone-400" />
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="John Doe"
                  required
                  className="w-full pl-12 pr-4 py-3 rounded-xl border border-stone-200 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-stone-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  required
                  className="w-full pl-12 pr-4 py-3 rounded-xl border border-stone-200 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-stone-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className="w-full pl-12 pr-12 py-3 rounded-xl border border-stone-200 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
              
              {password.length > 0 && (
                <div className="mt-3 p-3 bg-stone-50 rounded-lg space-y-2">
                  {passwordChecks.map(check => (
                    <div key={check.id} className="flex items-center gap-2 text-sm">
                      {check.passed ? (
                        <Check className="w-4 h-4 text-green-500" />
                      ) : (
                        <X className="w-4 h-4 text-stone-300" />
                      )}
                      <span className={check.passed ? 'text-green-600' : 'text-stone-500'}>
                        {check.label}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Confirm Password
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-stone-400" />
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  className={`w-full pl-12 pr-12 py-3 rounded-xl border focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent ${
                    confirmPassword.length > 0
                      ? passwordsMatch
                        ? 'border-green-300 bg-green-50/50'
                        : 'border-red-300 bg-red-50/50'
                      : 'border-stone-200'
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
                >
                  {showConfirmPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
              {confirmPassword.length > 0 && !passwordsMatch && (
                <p className="text-sm text-red-500 mt-1">Passwords do not match</p>
              )}
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading || !allRequirementsMet || !passwordsMatch}
            className="w-full mt-6 py-3 bg-gradient-to-r from-orange-500 to-amber-500 text-white font-semibold rounded-xl hover:from-orange-600 hover:to-amber-600 transition-all shadow-lg shadow-orange-500/25 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <>
                Create Account
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>

          <p className="text-center text-stone-500 mt-6">
            Already have an account?{' '}
            <Link 
              to="/shop/login" 
              state={{ from }}
              className="text-orange-600 hover:text-orange-700 font-medium"
            >
              Sign in
            </Link>
          </p>
        </form>

        <p className="text-center text-stone-400 text-sm mt-6">
          <Link to="/shop" className="hover:text-stone-600">
            ← Back to Shop
          </Link>
        </p>
      </div>
    </div>
  );
}
