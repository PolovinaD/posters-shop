import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Users as UsersIcon, Plus, Trash2, Shield, AlertTriangle, LogIn, Key } from 'lucide-react';
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
  Modal,
  Input,
  Select
} from '../components/ui';
import { usersApi } from '../api';

// Simple token storage (in production, use proper auth context)
const TOKEN_KEY = 'admin_token';

function LoginForm({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    
    try {
      const result = await usersApi.login(email, password);
      localStorage.setItem(TOKEN_KEY, result.access_token);
      onLogin(result.access_token);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="max-w-md mx-auto mt-12">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LogIn className="w-5 h-5" />
          Admin Login Required
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-slate-400 mb-6">
          You need to be logged in as an owner to manage users.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@postershop.com"
            required
          />
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            required
          />
          {error && (
            <div className="flex items-center gap-2 text-red-400 text-sm">
              <AlertTriangle className="w-4 h-4" />
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" loading={loading}>
            Login
          </Button>
        </form>
        <div className="mt-4 p-3 bg-slate-800 rounded-lg text-sm text-slate-400">
          <p className="font-medium text-slate-300 mb-1">Demo credentials:</p>
          <p>Email: admin@postershop.com</p>
          <p>Password: admin1234</p>
        </div>
      </CardContent>
    </Card>
  );
}

function CreateUserModal({ open, onClose, token }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    email: '',
    password: '',
    role: 'customer',
    first_name: '',
    last_name: '',
  });
  
  const mutation = useMutation({
    mutationFn: (data) => usersApi.createUser(token, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['users']);
      onClose();
      setForm({ email: '', password: '', role: 'customer', first_name: '', last_name: '' });
    },
  });
  
  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate(form);
  };
  
  const roleOptions = [
    { value: 'customer', label: 'Customer' },
    { value: 'courier', label: 'Courier' },
    { value: 'owner', label: 'Owner (Admin)' },
  ];
  
  return (
    <Modal open={open} onClose={onClose} title="Create New User">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="First Name"
            value={form.first_name}
            onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            placeholder="John"
          />
          <Input
            label="Last Name"
            value={form.last_name}
            onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            placeholder="Doe"
          />
        </div>
        <Input
          label="Email"
          type="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          placeholder="user@example.com"
          required
        />
        <Input
          label="Temporary Password"
          type="password"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          placeholder="Min 8 characters"
          required
        />
        <Select
          label="Role"
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
          options={roleOptions}
        />
        
        <div className="p-3 bg-blue-500/10 rounded-lg text-sm text-blue-400">
          <p>The user will be able to change their password after first login.</p>
        </div>
        
        {mutation.error && (
          <p className="text-red-400 text-sm">{mutation.error.message}</p>
        )}
        
        <div className="flex justify-end gap-3">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            Create User
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ChangeRoleModal({ open, onClose, user, token }) {
  const queryClient = useQueryClient();
  const [role, setRole] = useState(user?.role || 'customer');
  
  const mutation = useMutation({
    mutationFn: (newRole) => usersApi.changeUserRole(token, user.id, newRole),
    onSuccess: () => {
      queryClient.invalidateQueries(['users']);
      onClose();
    },
  });
  
  useEffect(() => {
    if (user) setRole(user.role);
  }, [user]);
  
  if (!user) return null;
  
  const roleOptions = [
    { value: 'customer', label: 'Customer' },
    { value: 'courier', label: 'Courier' },
    { value: 'owner', label: 'Owner (Admin)' },
  ];
  
  return (
    <Modal open={open} onClose={onClose} title={`Change Role: ${user.email}`}>
      <div className="space-y-4">
        <div className="p-3 bg-slate-800 rounded-lg">
          <p className="text-sm text-slate-400">Current role:</p>
          <p className="font-medium">{user.role}</p>
        </div>
        
        <Select
          label="New Role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          options={roleOptions}
        />
        
        {mutation.error && (
          <p className="text-red-400 text-sm">{mutation.error.message}</p>
        )}
        
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button 
            onClick={() => mutation.mutate(role)} 
            loading={mutation.isPending}
            disabled={role === user.role}
          >
            Update Role
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function UserManagement({ token, onLogout }) {
  const queryClient = useQueryClient();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [roleChangeUser, setRoleChangeUser] = useState(null);
  
  const { data: users, isLoading, error, refetch } = useQuery({
    queryKey: ['users', token],
    queryFn: () => usersApi.getUsers(token),
    retry: false,
    onError: (err) => {
      if (err.message.includes('401') || err.message.includes('403')) {
        localStorage.removeItem(TOKEN_KEY);
        onLogout();
      }
    },
  });
  
  const deleteMutation = useMutation({
    mutationFn: (id) => usersApi.deleteUser(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries(['users']);
    },
  });
  
  const handleDelete = (user) => {
    if (confirm(`Are you sure you want to delete ${user.email}?`)) {
      deleteMutation.mutate(user.id);
    }
  };
  
  const getRoleBadgeClass = (role) => {
    switch (role) {
      case 'owner': return 'bg-purple-500/20 text-purple-400';
      case 'courier': return 'bg-blue-500/20 text-blue-400';
      default: return 'bg-slate-500/20 text-slate-400';
    }
  };
  
  if (isLoading) return <Loading />;
  
  if (error) {
    if (error.message.includes('401') || error.message.includes('403')) {
      return <ErrorMessage message="Session expired. Please login again." retry={onLogout} />;
    }
    return <ErrorMessage message={error.message} retry={refetch} />;
  }
  
  const usersByRole = {
    owner: users?.filter(u => u.role === 'owner') || [],
    courier: users?.filter(u => u.role === 'courier') || [],
    customer: users?.filter(u => u.role === 'customer') || [],
  };
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Users</h1>
          <p className="text-slate-400">Manage users and their roles</p>
        </div>
        <div className="flex gap-3">
          <Button variant="ghost" onClick={onLogout}>
            <Key className="w-4 h-4" />
            Logout
          </Button>
          <Button onClick={() => setCreateModalOpen(true)}>
            <Plus className="w-4 h-4" />
            Add User
          </Button>
        </div>
      </div>
      
      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Owners</p>
            <p className="text-2xl font-bold text-purple-400">{usersByRole.owner.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Couriers</p>
            <p className="text-2xl font-bold text-blue-400">{usersByRole.courier.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Customers</p>
            <p className="text-2xl font-bold text-slate-300">{usersByRole.customer.length}</p>
          </CardContent>
        </Card>
      </div>
      
      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UsersIcon className="w-5 h-5" />
            All Users
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {users && users.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>ID</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead></TableHead>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-mono text-slate-400">#{user.id}</TableCell>
                    <TableCell className="font-medium">{user.email}</TableCell>
                    <TableCell className="text-slate-300">
                      {user.first_name || user.last_name 
                        ? `${user.first_name || ''} ${user.last_name || ''}`.trim()
                        : <span className="text-slate-500">—</span>
                      }
                    </TableCell>
                    <TableCell>
                      <span className={`px-2 py-1 rounded text-xs font-medium ${getRoleBadgeClass(user.role)}`}>
                        {user.role}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button 
                          size="sm" 
                          variant="secondary"
                          onClick={() => setRoleChangeUser(user)}
                        >
                          <Shield className="w-3 h-3" />
                          Role
                        </Button>
                        <Button 
                          size="sm" 
                          variant="danger"
                          onClick={() => handleDelete(user)}
                          loading={deleteMutation.isPending}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={UsersIcon}
              title="No users yet"
              description="Create your first user to get started"
              action={
                <Button onClick={() => setCreateModalOpen(true)}>
                  <Plus className="w-4 h-4" />
                  Add User
                </Button>
              }
            />
          )}
        </CardContent>
      </Card>
      
      {/* Modals */}
      <CreateUserModal 
        open={createModalOpen} 
        onClose={() => setCreateModalOpen(false)} 
        token={token}
      />
      <ChangeRoleModal
        open={!!roleChangeUser}
        onClose={() => setRoleChangeUser(null)}
        user={roleChangeUser}
        token={token}
      />
    </div>
  );
}

export default function Users() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  
  const handleLogin = (newToken) => {
    setToken(newToken);
  };
  
  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  };
  
  if (!token) {
    return <LoginForm onLogin={handleLogin} />;
  }
  
  return <UserManagement token={token} onLogout={handleLogout} />;
}

