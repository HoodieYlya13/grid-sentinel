pipeline {
    agent any

    environment {
        PYTHON_ENV  = 'django_control_plane'
        IMAGE_NAME  = 'sciops-grid-sentinel-dashboard'
        REGISTRY    = 'cern-local-registry:5000'
    }

    stages {
        stage('1. Code Checkout') {
            steps {
                echo 'Checking out source control branch...'
                checkout scm
            }
        }

        stage('2. Linting & Static Analysis') {
            parallel {
                stage('Python Code Linting') {
                    steps {
                        echo 'Running Flake8 & Black Python check...'
                        dir("${PYTHON_ENV}") {
                            sh 'pip install flake8 black --quiet'
                            sh 'black --check .'
                            sh 'flake8 --exclude=config/settings.py,nodes/migrations/ .'
                        }
                    }
                }

                stage('Terraform Validation') {
                    steps {
                        echo 'Initializing and validating Terraform templates...'
                        dir('terraform') {
                            sh 'terraform init -backend=false'
                            sh 'terraform validate'
                        }
                    }
                }

                stage('Puppet Code Linting') {
                    steps {
                        echo 'Validating Puppet manifests...'
                        sh 'gem install puppet-lint --no-document'
                        sh 'puppet-lint puppet/'
                    }
                }

                stage('Ansible Playbook Linting') {
                    steps {
                        echo 'Validating Ansible playbooks...'
                        sh 'pip install ansible-lint --quiet'
                        sh 'ansible-lint ansible/playbooks/'
                    }
                }
            }
        }

        stage('3. Run Django Unit Tests') {
            steps {
                echo 'Running Django unit tests and test suites...'
                dir("${PYTHON_ENV}") {
                    sh 'pip install -r requirements.txt --quiet'
                    sh 'python manage.py test'
                }
            }
        }

        stage('4. Docker Container Compilation') {
            steps {
                echo 'Building and packaging the Control Plane Docker image...'
                dir("${PYTHON_ENV}") {
                    sh "docker build -t ${IMAGE_NAME}:${env.BUILD_NUMBER} ."
                    sh "docker tag ${IMAGE_NAME}:${env.BUILD_NUMBER} ${REGISTRY}/${IMAGE_NAME}:${env.BUILD_NUMBER}"
                }
            }
        }

        stage('5. Dev Environment Deploy') {
            steps {
                echo 'Mock-deploying containers to development environment...'
                sh 'docker compose down --remove-orphans'
                sh 'docker compose up -d'
                echo 'Grid Sentinel cluster started successfully.'
            }
        }
    }

    post {
        success {
            echo 'Pipeline completed successfully. All validations passed.'
        }
        failure {
            echo 'Pipeline execution failed. Review build output logs.'
        }
    }
}
