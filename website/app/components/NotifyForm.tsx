'use client';

import { useState, FormEvent } from 'react';
import styles from './NotifyForm.module.css';

export default function NotifyForm() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    company: '',
    title: '',
  });
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus('loading');
    setMessage('');

    try {
      const response = await fetch('/api/notify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      const data = await response.json();

      if (response.ok) {
        setStatus('success');
        setMessage(data.message);
        setFormData({ name: '', email: '', company: '', title: '' });
      } else {
        setStatus('error');
        setMessage(data.error || 'Something went wrong. Please try again.');
      }
    } catch (error) {
      setStatus('error');
      setMessage('Network error. Please try again.');
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  return (
    <div className={styles.formWrapper}>
      <div className={styles.formHeader}>
        <h3 className={styles.formTitle}>Stay updated</h3>
        <p className={styles.formDescription}>
          Get notified when we release updates, new features, and production-ready tooling.
        </p>
      </div>

      <form onSubmit={handleSubmit} className={styles.form}>
        <div className={styles.formGrid}>
          <div className={styles.formGroup}>
            <label htmlFor="name" className={styles.label}>
              Name
            </label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              required
              disabled={status === 'loading'}
              className={styles.input}
              placeholder="Jane Smith"
            />
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="email" className={styles.label}>
              Email
            </label>
            <input
              type="email"
              id="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              required
              disabled={status === 'loading'}
              className={styles.input}
              placeholder="jane@company.com"
            />
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="company" className={styles.label}>
              Company
            </label>
            <input
              type="text"
              id="company"
              name="company"
              value={formData.company}
              onChange={handleChange}
              required
              disabled={status === 'loading'}
              className={styles.input}
              placeholder="Acme Corp"
            />
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="title" className={styles.label}>
              Title
            </label>
            <input
              type="text"
              id="title"
              name="title"
              value={formData.title}
              onChange={handleChange}
              required
              disabled={status === 'loading'}
              className={styles.input}
              placeholder="Engineering Lead"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={status === 'loading'}
          className={`${styles.submitBtn} ${status === 'loading' ? styles.loading : ''}`}
        >
          {status === 'loading' ? 'Sending...' : 'Notify me'}
          {status !== 'loading' && <span className={styles.btnArrow}>→</span>}
        </button>

        {message && (
          <div className={`${styles.message} ${status === 'success' ? styles.success : styles.error}`}>
            {message}
          </div>
        )}
      </form>
    </div>
  );
}
