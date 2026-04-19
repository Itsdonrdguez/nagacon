import React from 'react'
import { Button, Card } from './ui'

export default class RouteErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || 'Unexpected application error',
    }
  }

  componentDidCatch(error) {
    console.error('Route render error', error)
  }

  handleReset = () => {
    this.setState({ hasError: false, message: '' })
    window.location.assign('/opportunities')
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="page">
          <Card>
            <div className="route-error-state">
              <h2 className="empty-state-title">This page hit an error</h2>
              <p className="empty-state-subtitle">
                {this.state.message || 'Something went wrong while loading this screen.'}
              </p>
              <div className="empty-state-action">
                <Button onClick={this.handleReset}>Go to opportunities</Button>
              </div>
            </div>
          </Card>
        </div>
      )
    }

    return this.props.children
  }
}
