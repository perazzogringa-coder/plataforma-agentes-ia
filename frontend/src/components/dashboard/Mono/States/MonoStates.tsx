import React from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';

interface FullPageProps {
  isDark: boolean;
}

export const MonoLoading: React.FC<FullPageProps> = ({ isDark }) => (
  <div className={`mono-dashboard ${isDark ? 'mono-dashboard--dark' : ''}`}>
      <div className="mono-loading-page">
        <div className="mono-loading-box">
          <Loader2 aria-label="Carregando métricas" className="mono-spinner-svg" role="status" />
          <p>Carregando métricas...</p>
        </div>
      </div>
    </div>
  </div>
);

interface ErrorPageProps extends FullPageProps {
  error: string;
  onRefresh: () => void;
}

export const MonoError: React.FC<ErrorPageProps> = ({ error, isDark, onRefresh }) => (
  <div className={`mono-dashboard ${isDark ? 'mono-dashboard--dark' : ''}`}>
      <div className="mono-error-page">
        <div className="mono-error-box">
          <h1 className="mono-title">Erro ao carregar dados</h1>
          <div className="mono-alert mono-alert--danger mono-error-alert" role="alert">
            <AlertCircle aria-hidden="true" className="mono-alert-icon" />
            <span>{error}</span>
          </div>
          <button className="mono-btn mono-btn--primary" onClick={onRefresh} type="button">
            <RefreshCw />
            Tentar novamente
          </button>
          </div>
        </div>
      </div>
    </div>
  </div>
);

interface EmptyProps {
  children: React.ReactNode;
}

export const MonoEmpty: React.FC<EmptyProps> = ({ children }) => (
  <div className="mono-empty">{children}</div>
);

interface SkeletonProps {
  height?: number | string;
  width?: number | string;
  radius?: number | string;
  style?: React.CSSProperties;
}

export const MonoSkeleton: React.FC<SkeletonProps> = ({ height = 16, radius, style, width = '100%' }) => (
  <div
    aria-hidden="true"
    className="mono-skeleton"
    style={{ height, width, borderRadius: radius, ...style }}
  />
);

/** Estado vazio de chart: 0 datapoints -> placeholder; 1 datapoint -> aviso de ponto isolado. */
export const MonoChartEmpty: React.FC<{ singlePoint?: boolean }> = ({ singlePoint }) => (
  <div className="mono-empty">
    {singlePoint
      ? 'Apenas 1 ponto de dado no período — ajuste o intervalo para ver a linha.'
      : 'Sem dados no período selecionado.'}
  </div>
);
