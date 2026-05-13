'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import NotifyForm from './NotifyForm';
import styles from './NotifyDialog.module.css';

export default function NotifyDialog() {
  const [isOpen, setIsOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, []);

  return (
    <>
      <button onClick={() => setIsOpen(true)} className="btn">
        Get notified <span className="btn-arrow">→</span>
      </button>

      {mounted && isOpen && createPortal(
        <div className={styles.overlay} onClick={() => setIsOpen(false)}>
          <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
            <button
              className={styles.closeBtn}
              onClick={() => setIsOpen(false)}
              aria-label="Close dialog"
            >
              ✕
            </button>
            <NotifyForm />
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
