import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw, Undo2 } from 'lucide-react'
import { sanitizedErrorContext } from '../dataSafety'

type Props = { children: ReactNode; resetKey: string; onOverview: () => void }
type State = { error?: Error; retry: number }

export class ContentErrorBoundary extends Component<Props, State> {
  state: State = { retry: 0 }

  static getDerivedStateFromError(error: Error): State {
    return { error, retry: 0 }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Falha recuperável no conteúdo operacional', {
      ...sanitizedErrorContext(error),
      componentStack: info.componentStack?.slice(0, 1200),
    })
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: undefined, retry: 0 })
    }
  }

  retry = () => this.setState((state) => ({ error: undefined, retry: state.retry + 1 }))

  render() {
    if (!this.state.error) return <div key={this.state.retry}>{this.props.children}</div>
    return <section className="panel content-error" role="alert">
      <AlertTriangle size={26}/>
      <h2>Não foi possível exibir esta informação</h2>
      <p>Um dado operacional incompleto interrompeu somente este conteúdo. O menu e o restante do painel continuam disponíveis.</p>
      <div>
        <button type="button" className="primary-button" onClick={this.retry}><RefreshCw size={15}/>Tentar novamente</button>
        <button type="button" className="secondary-button" onClick={this.props.onOverview}><Undo2 size={15}/>Voltar à visão geral</button>
      </div>
    </section>
  }
}
