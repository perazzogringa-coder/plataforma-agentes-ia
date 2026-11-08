import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Check, LogOut, Menu, X, type LucideIcon } from 'lucide-react';
import type { UserCompany } from '../../services/api';
import styles from './MobileNav.module.css';

interface MobileNavItemProps {
  icon: LucideIcon | React.FC<any>;
  label: string;
  isActive: boolean;
  path: string;
  status?: string;
}

export const MobileNavItem: React.FC<MobileNavItemProps> = ({
  icon: Icon,
  label,
  isActive,
  path,
  status
}) => {
  return (
    <Link
      to={path}
      className={`${styles.navItem} ${isActive ? styles.navItemActive : styles.navItemInactive}`}
      aria-current={isActive ? 'page' : undefined}
    >
      <div className={styles.iconContainer}>
        <Icon className={styles.icon} />
        {status === 'connected' && (
          <div className={styles.statusBadge} />
        )}
      </div>
      <span className={styles.label}>
        {label}
      </span>
    </Link>
  );
};

interface MobileNavProps {
  activeCompanyId: string | null;
  companies: UserCompany[];
  menuItems: {
    path: string;
    icon: LucideIcon | React.FC<any>;
    label: string;
    isActive: boolean;
    status?: string;
  }[];
  moreMenuItems: {
    path: string;
    icon: LucideIcon | React.FC<any>;
    label: string;
    section: string;
    isActive: boolean;
  }[];
  onLogout: () => void;
  onSelectCompany: (id: number) => void;
}

const MobileNav: React.FC<MobileNavProps> = ({ activeCompanyId, companies, menuItems, moreMenuItems, onLogout, onSelectCompany }) => {
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  return (
    <nav className={styles.navContainer} data-agentive-mobile-nav="true">
      {isMenuOpen && (
        <>
          <button
            type="button"
            className={styles.menuBackdrop}
            onClick={() => setIsMenuOpen(false)}
            aria-label="Fechar menu"
          />
          <section id="mobile-full-menu" className={styles.menuSheet} aria-label="Menu completo">
            <div className={styles.menuSheetHeader}>
              <div>
                <p className={styles.menuEyebrow}>Navegação</p>
                <h2 className={styles.menuTitle}>Menu completo</h2>
              </div>
              <button type="button" className={styles.menuCloseButton} onClick={() => setIsMenuOpen(false)} aria-label="Fechar menu">
                <X className={styles.icon} />
              </button>
            </div>
            <div className={styles.menuList}>
              {companies.length > 0 && (
                <div className={styles.companySection}>
                  <p className={styles.menuSection}>Empresa</p>
                  {companies.map((company) => {
                    const isActiveCompany = company.company_id.toString() === activeCompanyId;
                    const companyName = company.name_company || `Empresa ${company.company_id}`;

                    return (
                      <button
                        key={company.company_id}
                        type="button"
                        className={`${styles.companyButton} ${isActiveCompany ? styles.companyButtonActive : ''}`}
                        onClick={() => {
                          setIsMenuOpen(false);
                          onSelectCompany(company.company_id);
                        }}
                      >
                        <Building2 className={styles.icon} />
                        <span>{companyName}</span>
                        {isActiveCompany && <Check className={styles.companyCheck} />}
                      </button>
                    );
                  })}
                </div>
              )}
              {moreMenuItems.map((item, index) => {
                const Icon = item.icon;
                const showSection = index === 0 || moreMenuItems[index - 1].section !== item.section;
                return (
                  <React.Fragment key={item.path}>
                    {showSection && <p className={styles.menuSection}>{item.section}</p>}
                    <Link
                      to={item.path}
                      className={`${styles.menuLink} ${item.isActive ? styles.menuLinkActive : ''}`}
                      onClick={() => setIsMenuOpen(false)}
                      aria-current={item.isActive ? 'page' : undefined}
                    >
                      <Icon className={styles.icon} />
                      <span>{item.label}</span>
                    </Link>
                  </React.Fragment>
                );
              })}
            </div>
          </section>
        </>
      )}
      <div className={styles.glassContainer}>
        {menuItems.map((item) => (
          <MobileNavItem
            key={item.path}
            icon={item.icon}
            label={item.label}
            isActive={item.isActive}
            path={item.path}
            status={item.status}
          />
        ))}
        <button
          type="button"
          onClick={() => setIsMenuOpen(true)}
          className={styles.menuButton}
          aria-expanded={isMenuOpen}
          aria-controls="mobile-full-menu"
        >
          <Menu className={styles.icon} />
          <span className={styles.label}>Menu</span>
        </button>
        <button
          type="button"
          onClick={onLogout}
          className={styles.logoutButton}
          aria-label="Sair da conta"
        >
          <LogOut className={styles.icon} />
          <span className={styles.label}>Sair</span>
        </button>
      </div>
    </nav>
  );
};

export default MobileNav;
