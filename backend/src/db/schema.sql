CREATE TABLE recipe_meta (
    recipe_id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    servings INT NOT NULL,
    preptime_minutes INT NOT NULL,
    cooktime_minutes INT NOT NULL,
    continent VARCHAR(100),
    source VARCHAR(255),
    source_url VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ingredients (
    ingredient_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE
);

CREATE TABLE recipe_steps (
    step_id SERIAL PRIMARY KEY,
    recipe_id INT NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    instruction TEXT NOT NULL,
    next_step_id INT REFERENCES recipe_steps(step_id) ON DELETE SET NULL, 
    duration_text VARCHAR(100),
    UNIQUE (recipe_id, step_number)
);

CREATE TABLE recipe_ingredients (
    recipe_ingredient_id SERIAL PRIMARY KEY,
    recipe_id INT NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
    ingredient_id INT NOT NULL REFERENCES ingredients(ingredient_id) ON DELETE CASCADE,
    step_id INT REFERENCES recipe_steps(step_id) ON DELETE CASCADE, 
    amount DECIMAL(6, 2),
    unit VARCHAR(50),
    prep_method VARCHAR(100)
);


CREATE TABLE tags (
    tag_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100)
);

CREATE TABLE recipe_tags (
    recipe_id INT NOT NULL REFERENCES recipe_meta(recipe_id) ON DELETE CASCADE,
    tag_id INT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, tag_id)
);