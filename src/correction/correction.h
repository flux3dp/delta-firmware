
struct CorrectionData {
    float max_pos[3];
    // float delta_radius = 96.7;
    float delta_radius;
    float DELTA_DIAGONAL_ROD_2;
    // float tower_adj[6] = {0};
    float tower_adj[6];
    float endstop_adj[3];
};

struct CorrectionResult {
    float X, Y, Z, R, H;
};

int calculator(float init_endstop_x, float init_endstop_y, float init_endstop_z,
               float init_endstop_h, float input_x, float input_y,
               float input_z, float input_h, float delta_radious, float t1x,
               float t1y, float t2x, float t2y, float t3x, float t3y, 
               struct CorrectionResult *result);
