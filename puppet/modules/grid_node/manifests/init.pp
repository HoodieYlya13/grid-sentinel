# Class: grid_node
#
# This class manages the configuration and state of a simulated WLCG grid node.
# It takes parameters dynamically supplied by the Django Control Plane (ENC).
#
class grid_node (
  String $role           = 'worker',
  Integer $thread_count  = 4,
  String $metrics_server = 'http://django:8000/api/metrics/',
  String $environment    = 'production',
) {

  # 1. Ensure target configuration directory exists
  file { '/etc/grid':
    ensure => directory,
    owner  => 'root',
    group  => 'root',
    mode   => '0755',
  }

  # 2. Template the configuration values into a local JSON config
  file { '/etc/grid/node_config.json':
    ensure  => file,
    owner   => 'root',
    group   => 'root',
    mode    => '0644',
    content => inline_template('
{
  "hostname": "<%= @fqdn %>",
  "role": "<%= @role %>",
  "thread_count": <%= @thread_count %>,
  "metrics_server": "<%= @metrics_server %>",
  "environment": "<%= @environment %>",
  "configured_at": "<%= Time.now.strftime("%Y-%m-%d %H:%M:%S") %>"
}
'),
    require => File['/etc/grid'],
  }

  # 3. Simulate starting the local workload processor service
  # In a real environment, this would declare a Service resource
  notify { "Node configured: FQDN=${fqdn}, Role=${role}, Environment=${environment}, ThreadCount=${thread_count}":
    require => File['/etc/grid/node_config.json'],
  }
}
