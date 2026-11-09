import { useEffect } from 'react';

/** Identity and PIN authorization belong to the Controller's OAuth flow. */
export default function Login() {
  useEffect(() => {
    window.location.replace('/auth/login');
  }, []);

  return <p role="status">Opening authentication…</p>;
}
