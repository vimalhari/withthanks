pipeline {
    agent any

    environment {
        DOCKER_IMAGE = "withthanks-django"
        IMAGE_TAG = "1.0.0"
        CONTAINER_NAME = "withthanks-container"
        APP_PORT = "8000"
        DOCKER_HUB_USER = "rankraze"  // your Docker Hub username
    }

    stages {
        stage('Checkout Code') {
            steps {
                echo "📂 Checking out source code..."
                git branch: 'main',
                    credentialsId: 'github-creds-1',
                    url: 'https://github.com/Rajachellan/WithThanks.git'
            }
        }

        stage('Docker Login') {
            steps {
                echo "🔐 Logging in to Docker Hub..."
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                    sh '''
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    '''
                }
            }
        }

        stage('Build & Push Docker Image') {
            steps {
                echo "🐳 Building Docker image..."
                sh '''
                docker build -t $DOCKER_IMAGE:$IMAGE_TAG .

                echo "🏷️ Tagging image..."
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:latest

                echo "🚀 Pushing to Docker Hub..."
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:latest
                '''
            }
        }

        stage('Stop Old Container') {
            steps {
                echo "🛑 Stopping old container if running..."
                sh '''
                docker stop $CONTAINER_NAME || true
                docker rm $CONTAINER_NAME || true
                '''
            }
        }

        stage('Run New Container') {
            steps {
                echo "🚀 Starting new Django container..."
                sh '''
                docker run -d --name $CONTAINER_NAME \
                    --restart always \
                    -p $APP_PORT:8000 \
                    $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Deployment Successful! App running on port $APP_PORT"
        }
        failure {
            echo "❌ Deployment Failed! Check Jenkins logs."
        }
    }
}
