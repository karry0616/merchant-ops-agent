-- Merchant Agent MySQL Schema

CREATE TABLE IF NOT EXISTS conversation_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stage VARCHAR(50) NOT NULL COMMENT 'pre_sale/post_sale_address/post_sale_usage/after_sales',
    customer_question TEXT NOT NULL,
    merchant_response TEXT NOT NULL,
    product VARCHAR(255) DEFAULT '',
    category VARCHAR(255) DEFAULT '',
    tags VARCHAR(500) DEFAULT '' COMMENT 'comma-separated tags',
    outcome VARCHAR(100) DEFAULT '' COMMENT '成交/已解决/退款/换货/未解决',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_stage (stage),
    INDEX idx_product (product),
    INDEX idx_category (category),
    INDEX idx_created_at (created_at),
    FULLTEXT INDEX idx_fulltext (customer_question, merchant_response)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='商家历史对话记录';

CREATE TABLE IF NOT EXISTS conversation_embeddings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    record_id BIGINT NOT NULL,
    embedding_blob BLOB COMMENT 'Serialized embedding vector',
    dimension INT DEFAULT 1024,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES conversation_records(id) ON DELETE CASCADE,
    UNIQUE KEY uk_record_id (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话记录Embedding缓存（MySQL本地降级用）';
