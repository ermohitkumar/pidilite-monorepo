import { getSession } from '@/lib/auth/session';
import { redirect } from 'next/navigation';

const HomePage = async () => {
  const session = await getSession();

  if (session) {
    redirect('/reports');
  }

  redirect('/login');
}
export default HomePage;
