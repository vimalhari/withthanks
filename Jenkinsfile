pipeline {
    agent any

    environment {
        DOCKER_IMAGE      = "withthanks-django"
        IMAGE_TAG         = "1.0.0"
        CONTAINER_NAME    = "withthanks-container"
        APP_PORT          = "8000"
        DOCKER_HUB_USER   = "rankraze"
        // Host folder for media uploads — persistent storage
        HOST_UPLOADS_PATH = "/home/rankraze/uploads/video-generation/uploads"
        // Inside-container folder (used by Django as MEDIA_ROOT)
        CONTAINER_MEDIA_PATH = "/app/media"
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
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    '''
                }
            }
        }

        stage('Build & Push Docker Image') {
            steps {
                echo "🐳 Building and pushing Docker image..."
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

        stage('Prepare Uploads Directory') {
            steps {
                echo "📁 Ensuring uploads directory exists and is writable..."
                sh '''
                mkdir -p $HOST_UPLOADS_PATH
                chown -R jenkins:jenkins $HOST_UPLOADS_PATH
                chmod -R 775 $HOST_UPLOADS_PATH
                ls -ld $HOST_UPLOADS_PATH
                '''
            }
        }

        stage('Stop Old Container') {
            steps {
                echo "🛑 Stopping old container (if any)..."
                sh '''
                docker stop $CONTAINER_NAME || true
                docker rm $CONTAINER_NAME || true
                '''
            }
        }

        stage('Run New Container') {
            steps {
                echo "🚀 Starting new Django container with mapped volumes..."
                withCredentials([file(credentialsId: 'django-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                    echo "📦 Running Docker container..."
                    docker run -d --name $CONTAINER_NAME \
                        --restart always \
                        -p $APP_PORT:8000 \
                        --env-file $ENV_FILE \
                        -v $HOST_UPLOADS_PATH:$CONTAINER_MEDIA_PATH \
                        $DOCKER_HUB_USER/$DOCKER_IMAGE:$IMAGE_TAG
                    '''
                }
            }
        }

        stage('Run Django Migrations') {
            steps {
                echo "🛠 Running Django migrations..."
                sh '''
                docker exec -i $CONTAINER_NAME python manage.py migrate --noinput
                '''
            }
        }

        stage('Check Container Health') {
            steps {
                echo "🔍 Checking container logs..."
                sh '''
                sleep 5
                docker logs --tail 30 $CONTAINER_NAME
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Deployment successful! Django is running on port $APP_PORT."
        }
        failure {
            echo "❌ Deployment failed! Please check Jenkins logs."
        }
        always {
            echo "📋 Pipeline finished at $(date)"
        }
    }
}
