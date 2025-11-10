pipeline {
    agent any

    environment {
        DOCKER_IMAGE = "withthanks-django"
        IMAGE_TAG = "1.0.0"
        CONTAINER_NAME = "withthanks-django-container"
        APP_PORT = "8000"
        HOST_MEDIA = "/home/withthanks/media"
        HOST_LOGS = "/home/withthanks/logs"
        HOST_ENV = "/home/withthanks/env"
        DOCKER_HUB_USER = "rankraze"    // replace with your Docker Hub username
    }

    stages {
        stage('Checkout Code') {
            steps {
                git branch: 'main',
                    credentialsId: 'github-creds-1',
                    url: 'https://github.com/Rajachellan/WithThanks.git'
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                echo "📦 Installing Python dependencies..."
                pip install --upgrade pip
                pip install -r requirements.txt
                '''
            }
        }

        stage('Docker Login') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                    sh 'echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin'
                }
            }
        }

        stage('Build and Push Docker Image') {
            steps {
                sh '''
                echo "🐳 Building Docker image..."
                docker build -t $DOCKER_IMAGE:$IMAGE_TAG .

                echo "🏷️ Tagging Docker image..."
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker tag $DOCKER_IMAGE:$IMAGE_TAG $DOCKER_HUB_USER/$DOCKER_IMAGE:latest

                echo "🚀 Pushing image to Docker Hub..."
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                docker push $DOCKER_HUB_USER/$DOCKER_IMAGE:latest
                '''
            }
        }

        stage('Stop Old Container') {
            steps {
                sh '''
                echo "🧹 Stopping old container (if exists)..."
                docker stop $CONTAINER_NAME || true
                docker rm $CONTAINER_NAME || true
                '''
            }
        }

        stage('Run New Container') {
            steps {
                sh '''
                echo "🚀 Starting new Django container..."
                docker run -d --name $CONTAINER_NAME \
                --restart always \
                -p $APP_PORT:8000 \
                -v $HOST_MEDIA:/app/media \
                -v $HOST_LOGS:/app/logs \
                -v $HOST_ENV:/app/.env \
                -e DJANGO_SETTINGS_MODULE=withthanks.settings \
                $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Deployment Successful! Django app running on port $APP_PORT"
        }
        failure {
            echo "❌ Deployment Failed! Check Jenkins logs for errors."
        }
    }
}
